"""
Cog XP & Niveaux
"""
import random
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_config, get_guild_color
from utils.checks import staff_only

XP_COOLDOWN = 60  # secondes
XP_PER_MESSAGE = (15, 25)
LEVEL_FORMULA = lambda lvl: 100 * (lvl ** 1.5)


def xp_for_level(level: int) -> int:
    return int(100 * (level ** 1.5))


def level_from_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
        xp -= xp_for_level(level)
    return level


def xp_in_current_level(xp: int) -> tuple[int, int, int]:
    """Retourne (xp_actuel, xp_requis_pour_next, level_actuel)"""
    level = level_from_xp(xp)
    if level == 0:
        return xp, xp_for_level(1), 1
    xp_needed = xp_for_level(level + 1)
    xp_at_level_start = sum(xp_for_level(i) for i in range(1, level + 1))
    xp_current = xp - xp_at_level_start
    return xp_current, xp_needed, level


class XPCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._xp_cooldowns = {}

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        """Gain XP par message (cooldown 60s)"""
        if message.author.bot or not message.guild:
            return
        col = get_collection("xp")
        if col is None:
            return

        key = f"{message.guild.id}_{message.author.id}"
        import time
        now = time.time()
        if self._xp_cooldowns.get(key, 0) + XP_COOLDOWN > now:
            return
        self._xp_cooldowns[key] = now

        # Multiplicateur XP
        config = await get_guild_config(message.guild.id)
        xp_multi = 1.0
        col_roles = get_collection("xp_multipliers")
        if col_roles is not None:
            doc = await col_roles.find_one({"guild_id": str(message.guild.id)})
            if doc:
                for r in message.author.roles:
                    if str(r.id) in doc.get("roles", {}):
                        xp_multi = max(xp_multi, doc["roles"][str(r.id)])
                        break

        xp_gain = int(random.randint(*XP_PER_MESSAGE) * xp_multi)
        doc = await col.find_one({"guild_id": str(message.guild.id), "user_id": str(message.author.id)})
        old_xp = doc.get("xp", 0) if doc else 0
        new_xp = old_xp + xp_gain

        await col.update_one(
            {"guild_id": str(message.guild.id), "user_id": str(message.author.id)},
            {"$set": {"xp": new_xp}},
            upsert=True
        )

        old_level = level_from_xp(old_xp)
        new_level = level_from_xp(new_xp)
        if new_level > old_level:
            cid = config.get("rank_announce_channel_id")
            if cid:
                ch = message.guild.get_channel(int(cid))
                if isinstance(ch, discord.TextChannel):
                    tmpl = config.get("level_up_msg") or "🎉 Félicitations {user} ! Niveau **{level}** !"
                    try:
                        txt = tmpl.format(
                            user=message.author.mention,
                            level=new_level,
                            server=message.guild.name,
                        )
                    except Exception:
                        txt = f"{message.author.mention} → niveau **{new_level}** !"
                    try:
                        await ch.send(
                            embed=success_embed(
                                "⬆️ Niveau obtenu !",
                                txt,
                                await get_guild_color(message.guild.id),
                            )
                        )
                    except Exception:
                        pass

    @commands.command(name="rank")
    async def rank(self, ctx, member: discord.Member = None):
        """Affiche le rang XP d'un membre (sans niveau ni rôles)"""
        try:
            member = member or ctx.author
            col = get_collection("xp")
            doc = await col.find_one({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
            xp = doc.get("xp", 0) if doc else 0

            cursor = col.find({"guild_id": str(ctx.guild.id)}).sort("xp", -1)
            rank_num = 1
            async for d in cursor:
                if d["user_id"] == str(member.id):
                    break
                rank_num += 1

            color = await get_guild_color(ctx.guild.id)
            config = await get_guild_config(ctx.guild.id)
            xp_name = config.get("xp_name", "XP")

            embed = discord.Embed(
                title=f"📊 Rang de {member.display_name}",
                color=color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Classement", value=f"#{rank_num}", inline=True)
            embed.add_field(name=f"{xp_name}", value=f"{xp:,}", inline=True)
            embed.set_footer(text="━━━━━━━━━━━━━━━━━━━━")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="rankembed")
    async def rankembed(self, ctx):
        """Poste un embed avec bouton pour afficher son rang XP."""
        try:
            color = await get_guild_color(ctx.guild.id)
            v = discord.ui.View(timeout=None)
            btn = discord.ui.Button(label="Afficher mon rank", style=discord.ButtonStyle.success, custom_id="xp:rank:show")

            async def cb(interaction: discord.Interaction):
                if not interaction.guild:
                    return
                col = get_collection("xp")
                doc = await col.find_one({"guild_id": str(interaction.guild.id), "user_id": str(interaction.user.id)})
                xp = doc.get("xp", 0) if doc else 0
                cursor = col.find({"guild_id": str(interaction.guild.id)}).sort("xp", -1)
                rank_num = 1
                async for d in cursor:
                    if d["user_id"] == str(interaction.user.id):
                        break
                    rank_num += 1
                cfg = await get_guild_config(interaction.guild.id)
                xp_name = cfg.get("xp_name", "XP")
                emb = discord.Embed(title="📊 Ton rang", color=await get_guild_color(interaction.guild.id))
                emb.add_field(name="Classement", value=f"#{rank_num}", inline=True)
                emb.add_field(name=xp_name, value=f"{xp:,}", inline=True)
                await interaction.response.send_message(embed=emb, ephemeral=True)

            btn.callback = cb
            v.add_item(btn)
            await ctx.send(
                embed=discord.Embed(
                    title="📊 Rank",
                    description="Clique pour afficher ton rang en privé.",
                    color=color,
                ),
                view=v,
            )
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


class XPRankPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        btn = discord.ui.Button(label="Afficher mon rank", style=discord.ButtonStyle.success, custom_id="xp:rank:show")

        async def cb(interaction: discord.Interaction):
            if not interaction.guild:
                return
            col = get_collection("xp")
            doc = await col.find_one({"guild_id": str(interaction.guild.id), "user_id": str(interaction.user.id)})
            xp = doc.get("xp", 0) if doc else 0
            cursor = col.find({"guild_id": str(interaction.guild.id)}).sort("xp", -1)
            rank_num = 1
            async for d in cursor:
                if d["user_id"] == str(interaction.user.id):
                    break
                rank_num += 1
            cfg = await get_guild_config(interaction.guild.id)
            xp_name = cfg.get("xp_name", "XP")
            emb = discord.Embed(title="📊 Ton rang", color=await get_guild_color(interaction.guild.id))
            emb.add_field(name="Classement", value=f"#{rank_num}", inline=True)
            emb.add_field(name=xp_name, value=f"{xp:,}", inline=True)
            await interaction.response.send_message(embed=emb, ephemeral=True)

        btn.callback = cb
        self.add_item(btn)

    @commands.command(name="leaderboard")
    async def leaderboard(self, ctx, page: int = 1):
        """Top 10 XP"""
        try:
            col = get_collection("xp")
            cursor = col.find({"guild_id": str(ctx.guild.id)}).sort("xp", -1).skip((page - 1) * 10).limit(10)
            lines = []
            medals = ["🥇", "🥈", "🥉"] + [f"**{i}**" for i in range(4, 11)]
            idx = 0
            async for doc in cursor:
                user = self.bot.get_user(int(doc["user_id"]))
                name = user.display_name if user else f"User {doc['user_id']}"
                xp = doc.get("xp", 0)
                medal = medals[idx] if idx < len(medals) else str(idx + 1)
                lines.append(f"{medal} **{name}** • {xp:,} XP")
                idx += 1

            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📊 Classement XP",
                description="\n".join(lines) if lines else "Aucun données",
                color=color,
            )
            embed.set_footer(text=f"Page {page} • +leaderboard [page]")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setxp")
    @staff_only()
    async def setxp(self, ctx, member: discord.Member, amount: int):
        """Définit l'XP d'un membre (admin)"""
        try:
            amount = max(0, amount)
            col = get_collection("xp")
            await col.update_one(
                {"guild_id": str(ctx.guild.id), "user_id": str(member.id)},
                {"$set": {"xp": amount}},
                upsert=True
            )
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("XP", f"XP de **{member}** : **{amount}**", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="resetxp")
    @staff_only()
    async def resetxp(self, ctx, member: discord.Member):
        """Réinitialise l'XP d'un membre (admin)"""
        try:
            col = get_collection("xp")
            await col.update_one(
                {"guild_id": str(ctx.guild.id), "user_id": str(member.id)},
                {"$set": {"xp": 0}},
                upsert=True
            )
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("XP", f"XP de **{member}** réinitialisé.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="xpmulti")
    @staff_only()
    async def xpmulti(self, ctx, role: discord.Role, multiplier: float):
        """Multiplicateur XP pour un rôle (ex: 2 = x2 XP)"""
        try:
            multiplier = max(0.1, min(10, multiplier))
            col = get_collection("xp_multipliers")
            await col.update_one(
                {"guild_id": str(ctx.guild.id)},
                {"$set": {f"roles.{role.id}": multiplier}},
                upsert=True
            )
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("XP Multiplicateur", f"Rôle {role.mention} : x{multiplier} XP", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(XPCog(bot))
    bot.add_view(XPRankPanelView(bot))
