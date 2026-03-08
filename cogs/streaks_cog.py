"""
Cog Streaks d'activité (style Snapchat)
"""
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color
from cogs.economy_cog import add_coins

STREAK_GOALS = {1: 5, 8: 15, 31: 30}  # jours -> messages
VOCAL_REQ = 30  # minutes à partir de 31j
STREAK_BONUS = 50  # coins par jour objectif atteint


def get_goal(streak_days: int) -> tuple[int, int]:
    """Retourne (messages_requis, vocal_min)"""
    msg = 5
    vocal = 0
    for threshold, m in sorted(STREAK_GOALS.items(), reverse=True):
        if streak_days >= threshold:
            msg = m
            if threshold >= 31:
                vocal = VOCAL_REQ
            break
    return msg, vocal


class StreaksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="streak")
    async def streak(self, ctx, member: discord.Member = None):
        """Affiche le streak actuel, objectif du jour, progression"""
        try:
            member = member or ctx.author
            col = get_collection("activity_streaks")
            if col is None:
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return
            doc = await col.find_one({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
            streak_days = doc.get("streak", 0) if doc else 0
            last_active = doc.get("last_date")  # ISO date string
            today = datetime.now(timezone.utc).date().isoformat()

            msg_col = get_collection("message_stats")
            vc_col = get_collection("voice_stats")
            msg_count = 0
            vc_count = 0
            if msg_col is not None:
                cur = msg_col.find({"guild_id": str(ctx.guild.id), "user_id": str(member.id), "date": today})
                async for d in cur:
                    msg_count += d.get("count", 0)
            if vc_col is not None:
                cur = vc_col.find({"guild_id": str(ctx.guild.id), "user_id": str(member.id), "date": today})
                async for d in cur:
                    vc_count += d.get("minutes", 0)

            msg_goal, vocal_goal = get_goal(streak_days)
            msg_bar = get_progress_bar(min(msg_count, msg_goal), msg_goal, 10)
            vocal_bar = get_progress_bar(min(vc_count, vocal_goal), vocal_goal or 1, 10) if vocal_goal else "N/A"

            color = await get_guild_color(ctx.guild.id)
            config = await get_guild_config(ctx.guild.id) or {}
            currency_emoji = config.get("currency_emoji", "💰")

            embed = discord.Embed(
                title=f"🔥 Streak — {member.display_name}",
                description=f"**Streak actuel:** {streak_days} jour(s) 🔥",
                color=color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Objectif messages", value=f"{msg_count}/{msg_goal} — {msg_bar}", inline=False)
            if vocal_goal:
                embed.add_field(name="Objectif vocal (min)", value=f"{vc_count}/{vocal_goal} — {vocal_bar}", inline=False)
            embed.add_field(name="Bonus", value=f"+{STREAK_BONUS} {currency_emoji} si objectif atteint", inline=False)
            embed.set_footer(text="1-7j: 5 msg/j | 8-30j: 15 msg/j | 31j+: 30 msg + 30min vocal")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="streakleaderboard")
    async def streakleaderboard(self, ctx):
        """Top 10 streaks"""
        try:
            col = get_collection("activity_streaks")
            if col is None:
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return
            cursor = col.find({"guild_id": str(ctx.guild.id)}).sort("streak", -1).limit(10)
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            idx = 0
            async for doc in cursor:
                user = self.bot.get_user(int(doc["user_id"]))
                name = user.display_name if user else f"User {doc['user_id']}"
                streak = doc.get("streak", 0)
                medal = medals[idx] if idx < 3 else f"**{idx + 1}**"
                lines.append(f"{medal} **{name}** — {streak} jour(s) 🔥")
                idx += 1
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="🔥 Top 10 Streaks",
                description="\n".join(lines) if lines else "Aucune donnée",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(StreaksCog(bot))
