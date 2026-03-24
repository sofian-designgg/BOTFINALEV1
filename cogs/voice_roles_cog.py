"""
Cog Rôles vocaux — paliers configurables par serveur (+addvoicerole, etc.)
"""
import discord
from discord.ext import commands
from database import is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_color, get_guild_config
from utils.embeds import get_progress_bar
from utils.milestone_roles import (
    get_total_voice_minutes,
    apply_voice_milestones,
    normalize_voice_milestones,
)


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
        """Après mise à jour du temps vocal (stats_cog), applique les rôles paliers."""
        if member.bot or not member.guild:
            return
        if not before.channel:
            return
        await apply_voice_milestones(self.bot, member)

    @commands.command(name="voiceprogress", aliases=["vocalprogress", "vp"])
    async def voiceprogress(self, ctx, member: discord.Member = None):
        """Avancement vers les rôles vocaux (paliers définis par +addvoicerole)"""
        try:
            member = member or ctx.author
            total_min = await get_total_voice_minutes(ctx.guild.id, member.id)
            total_h = total_min / 60
            color = await get_guild_color(ctx.guild.id)
            conf = await get_guild_config(ctx.guild.id)
            milestones = normalize_voice_milestones(conf.get("voice_role_milestones"))

            if not milestones:
                embed = discord.Embed(
                    title=f"🎤 Avancement vocal — {member.display_name}",
                    description="Aucun palier vocal configuré. Un admin peut utiliser `+addvoicerole @Rôle [minutes]` "
                    "puis `+setrankchannel #salon` pour les annonces.",
                    color=color,
                )
                embed.add_field(name="Temps total", value=f"**{total_h:.1f}h** ({total_min} min)", inline=False)
                await ctx.send(embed=embed)
                return

            lines = []
            for m in milestones:
                min_req = m["minutes"]
                role = ctx.guild.get_role(m["role_id"])
                role_name = role.name if role else f"Rôle {m['role_id']}"
                has_role = role and role in member.roles

                if total_min >= min_req:
                    lines.append(f"✅ **{role_name}** ({min_req} min) — Obtenu !")
                else:
                    progress = total_min / min_req if min_req else 0
                    bar = get_progress_bar(total_min, min_req, 12)
                    restant = min_req - total_min
                    h_rest = int(restant // 60)
                    m_rest = int(restant % 60)
                    rest_str = f"{h_rest}h{m_rest:02d}" if h_rest else f"{m_rest}min"
                    lines.append(
                        f"⬜ **{role_name}** ({min_req} min) — {bar} `{total_min}/{min_req}` min (encore {rest_str})"
                    )

            embed = discord.Embed(
                title=f"🎤 Avancement vocal — {member.display_name}",
                description=f"**Temps total : {total_h:.1f}h** ({total_min} min)\n\n" + "\n".join(lines),
                color=color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="Paliers : +addvoicerole @Rôle minutes · Annonces : +setrankchannel")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(VoiceRolesCog(bot))
