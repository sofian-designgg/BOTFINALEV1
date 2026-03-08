"""
Cog Vote / Fame / Profile / Duel
"""
import discord
from discord.ext import commands
from discord.ui import Button, View
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color


class DuelView(View):
    def __init__(self, bot, ctx, user1, user2, timeout=60):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.ctx = ctx
        self.user1 = user1
        self.user2 = user2
        self.votes1 = 0
        self.votes2 = 0
        self.voters = set()

        async def vote1_cb(interaction):
            await self.vote(interaction, 1)
        async def vote2_cb(interaction):
            await self.vote(interaction, 2)
        btn1 = Button(label="Vote 1", style=discord.ButtonStyle.primary, emoji="1️⃣", custom_id="vote1")
        btn2 = Button(label="Vote 2", style=discord.ButtonStyle.primary, emoji="2️⃣", custom_id="vote2")
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
        color_val = await get_guild_color(self.ctx.guild.id)
        embed = self.build_embed(color_val)
        await interaction.response.edit_message(embed=embed)

    def build_embed(self, color):
        embed = discord.Embed(
            title="⚔️ Duel de réputation",
            description=f"**{self.user1.display_name}** vs **{self.user2.display_name}**",
            color=color,
        )
        embed.set_thumbnail(url=self.user1.display_avatar.url)
        embed.add_field(name=f"1️⃣ {self.user1.display_name}", value=f"**{self.votes1}** votes", inline=True)
        embed.add_field(name=f"2️⃣ {self.user2.display_name}", value=f"**{self.votes2}** votes", inline=True)
        return embed


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
    async def duel(self, ctx, member: discord.Member):
        """Duel de réputation — 2 photos côte à côte, vote par boutons"""
        try:
            if member.bot or member.id == ctx.author.id:
                await ctx.send(embed=error_embed("Erreur", "Cible invalide."))
                return

            color = await get_guild_color(ctx.guild.id)
            view = DuelView(self.bot, ctx, ctx.author, member)
            embed = view.build_embed(color)
            embed.set_image(url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed, view=view)
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
