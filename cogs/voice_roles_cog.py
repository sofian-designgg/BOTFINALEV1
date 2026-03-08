"""
Cog Rôles vocaux - Rôles automatiques selon le temps passé en vocal
3h, 5h, 10h avec commande pour voir son avancement
"""
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_color
from utils.embeds import get_progress_bar

VOICE_ROLES = [
    (180, 1477766282299572254),   # 3h
    (300, 1477763567167082506),   # 5h
    (600, 1470854476859441242),   # 10h
]


async def get_total_voice_minutes(guild_id: str, user_id: str) -> int:
    """Retourne le total de minutes vocales d'un utilisateur"""
    col = get_collection("voice_stats")
    if col is None:
        return 0
    pipeline = [
        {"$match": {"guild_id": str(guild_id), "user_id": str(user_id)}},
        {"$group": {"_id": None, "total": {"$sum": "$minutes"}}}
    ]
    async for doc in col.aggregate(pipeline):
        return doc.get("total", 0)
    return 0


async def update_voice_roles(member: discord.Member, total_minutes: int) -> list:
    """Assigne les rôles vocaux selon le total. Retourne la liste des rôles ajoutés."""
    added = []
    for min_required, role_id in VOICE_ROLES:
        if total_minutes >= min_required:
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Temps vocal atteint")
                    added.append(role.name)
                except Exception:
                    pass
    return added


class VoiceRolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Vérifie et assigne les rôles après une sortie de vocal"""
        if member.bot or not member.guild:
            return
        if not before.channel:
            return
        total = await get_total_voice_minutes(str(member.guild.id), str(member.id))
        added = await update_voice_roles(member, total)
        if added:
            try:
                color = await get_guild_color(member.guild.id)
                embed = success_embed(
                    "🎤 Rôle vocal obtenu !",
                    f"{member.mention} a débloqué : {', '.join(f'`{r}`' for r in added)}",
                    color
                )
                await before.channel.send(embed=embed)
            except Exception:
                pass

    @commands.command(name="voiceprogress", aliases=["vocalprogress", "vp"])
    async def voiceprogress(self, ctx, member: discord.Member = None):
        """Affiche ton avancement vers les rôles vocaux (3h, 5h, 10h)"""
        try:
            member = member or ctx.author
            total_min = await get_total_voice_minutes(str(ctx.guild.id), str(member.id))
            total_h = total_min / 60
            color = await get_guild_color(ctx.guild.id)

            lines = []
            for min_req, role_id in VOICE_ROLES:
                h_req = min_req / 60
                role = ctx.guild.get_role(role_id)
                role_name = role.name if role else f"Rôle {role_id}"
                has_role = role and role in member.roles

                if total_min >= min_req:
                    lines.append(f"✅ **{role_name}** ({int(h_req)}h) — Obtenu !")
                else:
                    progress = total_min / min_req
                    bar = get_progress_bar(total_min, min_req, 12)
                    restant = min_req - total_min
                    h_rest = int(restant // 60)
                    m_rest = int(restant % 60)
                    rest_str = f"{h_rest}h{m_rest:02d}" if h_rest else f"{m_rest}min"
                    lines.append(f"⬜ **{role_name}** ({int(h_req)}h) — {bar} `{total_min}/{min_req}` min (encore {rest_str})")

            embed = discord.Embed(
                title=f"🎤 Avancement vocal — {member.display_name}",
                description=f"**Temps total : {total_h:.1f}h** ({total_min} min)\n\n" + "\n".join(lines),
                color=color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="Gagne des rôles en passant du temps en vocal !")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(VoiceRolesCog(bot))
