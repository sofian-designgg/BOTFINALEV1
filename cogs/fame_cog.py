"""
Cog Vote / Fame / Profile / Duel
"""
import discord
from discord.ext import commands
from discord.ui import Button, View
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color
from cogs.economy_cog import get_balance
from cogs.xp_cog import level_from_xp


async def get_member_stats(bot, guild_id: int, member: discord.Member) -> dict:
    """Récupère les stats d'un membre : rôle, argent, XP, fame, activité"""
    config = (await get_guild_config(guild_id)) or {}
    currency_emoji = config.get("currency_emoji", "💰")
    currency_name = config.get("currency_name", "SayuCoins")

    role = member.top_role.name if member.top_role and member.top_role.name != "@everyone" else "Aucun"
    money = await get_balance(guild_id, member.id)

    col_xp = get_collection("xp")
    xp = 0
    if col_xp is not None:
        doc = await col_xp.find_one({"guild_id": str(guild_id), "user_id": str(member.id)})
        xp = doc.get("xp", 0) if doc else 0
    level = level_from_xp(xp)

    col_fame = get_collection("fame")
    fame = 0
    if col_fame is not None:
        doc = await col_fame.find_one({"guild_id": str(guild_id), "user_id": str(member.id)})
        fame = doc.get("score", 0) if doc else 0

    col_msg = get_collection("message_stats")
    col_vc = get_collection("voice_stats")
    msg_count = 0
    vc_min = 0
    if col_msg is not None:
        pipeline = [{"$match": {"guild_id": str(guild_id), "user_id": str(member.id)}},
                    {"$group": {"_id": None, "total": {"$sum": "$count"}}}]
        async for d in col_msg.aggregate(pipeline):
            msg_count = d.get("total", 0)
            break
    if col_vc is not None:
        pipeline = [{"$match": {"guild_id": str(guild_id), "user_id": str(member.id)}},
                    {"$group": {"_id": None, "total": {"$sum": "$minutes"}}}]
        async for d in col_vc.aggregate(pipeline):
            vc_min = d.get("total", 0)
            break

    return {
        "role": role,
        "money": money,
        "currency_emoji": currency_emoji,
        "currency_name": currency_name,
        "xp": xp,
        "level": level,
        "fame": fame,
        "messages": msg_count,
        "vocal_min": vc_min,
    }


def build_duel_embed(member: discord.Member, stats: dict, votes: int, color: int, is_user1: bool):
    """Construit l'embed de profil pour un membre du duel"""
    num = "1️⃣" if is_user1 else "2️⃣"
    embed = discord.Embed(
        title=f"💮 {num} {member.display_name}",
        color=color,
    )
    embed.set_image(url=member.display_avatar.url)
    embed.add_field(name="👑 Rôle", value=stats["role"], inline=True)
    embed.add_field(name=f"{stats['currency_emoji']} Argent", value=f"{stats['money']:,} {stats['currency_name']}", inline=True)
    embed.add_field(name="⭐ Niveau", value=f"Niv. {stats['level']} ({stats['xp']:,} XP)", inline=True)
    embed.add_field(name="💮 Réputation", value=str(stats["fame"]), inline=True)
    embed.add_field(name="💬 Messages", value=f"{stats['messages']:,}", inline=True)
    embed.add_field(name="🔊 Vocal", value=f"{stats['vocal_min']} min", inline=True)
    embed.add_field(name="🗳️ Votes", value=f"**{votes}**", inline=False)
    return embed


class DuelView(View):
    def __init__(self, bot, ctx, user1, user2, stats1, stats2, color, timeout=60):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.ctx = ctx
        self.user1 = user1
        self.user2 = user2
        self.stats1 = stats1
        self.stats2 = stats2
        self.color = color
        self.votes1 = 0
        self.votes2 = 0
        self.voters = set()

        async def vote1_cb(interaction):
            await self.vote(interaction, 1)
        async def vote2_cb(interaction):
            await self.vote(interaction, 2)
        btn1 = Button(label=f"Vote {user1.display_name[:15]}", style=discord.ButtonStyle.secondary, emoji="1️⃣", custom_id="vote1")
        btn2 = Button(label=f"Vote {user2.display_name[:15]}", style=discord.ButtonStyle.secondary, emoji="2️⃣", custom_id="vote2")
        btn1.callback = vote1_cb
        btn2.callback = vote2_cb
        self.add_item(btn1)
        self.add_item(btn2)

    async def vote(self, interaction, choice):
        if interaction.user.id in self.voters:
            await interaction.response.send_message("Vous avez déjà voté.", ephemeral=True)
            return
        self.voters.add(interaction.user.id)
        if choice == 1:
            self.votes1 += 1
        else:
            self.votes2 += 1
        embeds = self.build_embeds()
        await interaction.response.edit_message(embeds=embeds)

    def build_embeds(self):
        e1 = build_duel_embed(self.user1, self.stats1, self.votes1, self.color, True)
        e2 = build_duel_embed(self.user2, self.stats2, self.votes2, self.color, False)
        return [e1, e2]


class FameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="vote")
    async def vote(self, ctx, member: discord.Member, vote_type: str):
        """+vote @user positive ou negative"""
        try:
            if member.bot or member.id == ctx.author.id:
                await ctx.send(embed=error_embed("Erreur", "Cible invalide."))
                return
            vote_type = vote_type.lower()
            if vote_type not in ("positive", "negative", "pos", "neg"):
                await ctx.send(embed=error_embed("Erreur", "Type: `positive` ou `negative`"))
                return
            delta = 1 if vote_type in ("positive", "pos") else -1
            col = get_collection("fame")
            await col.update_one(
                {"guild_id": str(ctx.guild.id), "user_id": str(member.id)},
                {"$inc": {"score": delta}},
                upsert=True
            )
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Vote", f"Vote {vote_type} enregistré pour **{member}**.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="fame")
    async def fame(self, ctx, member: discord.Member = None):
        """Profil de réputation avec photo grande"""
        try:
            member = member or ctx.author
            col = get_collection("fame")
            doc = await col.find_one({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
            score = doc.get("score", 0) if doc else 0

            # Rang
            cursor = col.find({"guild_id": str(ctx.guild.id)}).sort("score", -1)
            rank = 1
            async for d in cursor:
                if d["user_id"] == str(member.id):
                    break
                rank += 1

            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title=f"⭐ Profil réputation — {member.display_name}",
                description=f"**Score:** {score}\n**Rang:** #{rank}",
                color=color,
            )
            embed.set_image(url=member.display_avatar.url)
            embed.set_footer(text="━━━━━━━━━━━━━━━━━━━━")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="duel")
    async def duel(self, ctx, membre1: discord.Member = None, membre2: discord.Member = None):
        """+duel @personne1 @personne2 — Met en duel deux membres (organisé par le lead)"""
        try:
            if membre1 is None or membre2 is None:
                await ctx.send(embed=error_embed(
                    "Usage",
                    "Mentionne **les deux** personnes à mettre en duel :\n`+duel @personne1 @personne2` 💮"
                ))
                return
            if membre1.bot or membre2.bot:
                await ctx.send(embed=error_embed("Erreur", "Tu ne peux pas mettre un bot en duel."))
                return
            if membre1.id == membre2.id:
                await ctx.send(embed=error_embed("Erreur", "Les deux personnes doivent être différentes."))
                return

            color_val = await get_guild_color(ctx.guild.id)
            stats1 = await get_member_stats(self.bot, ctx.guild.id, membre1)
            stats2 = await get_member_stats(self.bot, ctx.guild.id, membre2)
            view = DuelView(self.bot, ctx, membre1, membre2, stats1, stats2, color_val)
            embeds = view.build_embeds()

            header = discord.Embed(
                title="💮 Duel de réputation",
                description=f"**{membre1.display_name}** vs **{membre2.display_name}**\n\n_Votez pour votre favori ci-dessous !_",
                color=color_val,
            )
            header.set_footer(text="Organisé par " + ctx.author.display_name)
            full_embeds = [header] + embeds
            await ctx.send(embeds=full_embeds, view=view)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="fameleaderboard")
    async def fameleaderboard(self, ctx):
        """Top 10 réputation"""
        try:
            col = get_collection("fame")
            cursor = col.find({"guild_id": str(ctx.guild.id)}).sort("score", -1).limit(10)
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            idx = 0
            async for doc in cursor:
                user = self.bot.get_user(int(doc["user_id"]))
                name = user.display_name if user else f"User {doc['user_id']}"
                score = doc.get("score", 0)
                medal = medals[idx] if idx < 3 else f"**{idx + 1}**"
                lines.append(f"{medal} **{name}** — {score} ⭐")
                idx += 1
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="⭐ Top 10 Réputation",
                description="\n".join(lines) if lines else "Aucune donnée",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(FameCog(bot))
