"""
Cog Statistiques & Graphiques
"""
import io
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color


def create_dark_chart(x_labels, y_values, title, color_hex="#8B5CF6"):
    """Crée un graphique matplotlib style sombre"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor('#1a1a2e')
        ax.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')
        for spine in ax.spines.values():
            spine.set_color('#4a4a6a')
        ax.set_xlabel('Jours')
        ax.set_ylabel('Valeur')
        ax.set_title(title)
        ax.grid(True, alpha=0.2, color='white')
        x = np.arange(len(x_labels))
        colors = plt.cm.viridis(np.linspace(0.3, 0.9, len(y_values)))
        ax.bar(x, y_values, color=colors, edgecolor='#8B5CF6', linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, color='white')
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#1a1a2e', edgecolor='none', dpi=100)
        buf.seek(0)
        plt.close()
        return buf
    except ImportError:
        return None


class StatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="stats")
    async def stats(self, ctx, member: discord.Member = None):
        """2 graphiques: messages (7j) + vocal (7j)"""
        try:
            member = member or ctx.author
            col_msg = get_collection("message_stats")
            col_vc = get_collection("voice_stats")
            labels = []
            msg_data = []
            vc_data = []
            now = datetime.now(timezone.utc)
            for i in range(6, -1, -1):
                d = (now - timedelta(days=i)).date()
                labels.append(d.strftime("%d/%m"))
                day_str = d.isoformat()
                cursor = col_msg.find({
                    "guild_id": str(ctx.guild.id),
                    "user_id": str(member.id),
                    "date": day_str
                })
                total = 0
                async for doc in cursor:
                    total += doc.get("count", 1)
                msg_data.append(total)
                # Vocal (minutes)
                cursor = col_vc.find({
                    "guild_id": str(ctx.guild.id),
                    "user_id": str(member.id),
                    "date": day_str
                })
                vc_total = 0
                async for doc in cursor:
                    vc_total += doc.get("minutes", 0)
                vc_data.append(vc_total)

            buf1 = create_dark_chart(labels, msg_data, f"Messages - {member.display_name}")
            buf2 = create_dark_chart(labels, vc_data, f"Vocal (min) - {member.display_name}")

            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title=f"📊 Statistiques de {member.display_name}",
                description="7 derniers jours",
                color=color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            if buf1:
                embed.set_image(url="attachment://messages.png")
                await ctx.send(embed=embed, files=[
                    discord.File(buf1, filename="messages.png"),
                    discord.File(buf2, filename="vocal.png") if buf2 else None
                ])
            else:
                embed.add_field(name="Messages", value=", ".join(map(str, msg_data)), inline=False)
                embed.add_field(name="Vocal (min)", value=", ".join(map(str, vc_data)), inline=False)
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="serverstats")
    async def serverstats(self, ctx):
        """Graphiques globaux du serveur"""
        try:
            col_msg = get_collection("message_stats")
            col_vc = get_collection("voice_stats")
            labels = []
            msg_data = []
            vc_data = []
            now = datetime.now(timezone.utc)
            for i in range(6, -1, -1):
                d = (now - timedelta(days=i)).date()
                labels.append(d.strftime("%d/%m"))
                day_str = d.isoformat()
                pipeline_msg = [{"$match": {"guild_id": str(ctx.guild.id), "date": day_str}},
                               {"$group": {"_id": None, "total": {"$sum": "$count"}}}]
                count_msg = 0
                async for doc in col_msg.aggregate(pipeline_msg):
                    count_msg = doc.get("total", 0)
                    break
                pipeline_vc = [{"$match": {"guild_id": str(ctx.guild.id), "date": day_str}},
                              {"$group": {"_id": None, "total": {"$sum": "$minutes"}}}]
                cur = col_vc.aggregate(pipeline_vc)
                vc_total = 0
                async for doc in cur:
                    vc_total = doc.get("total", 0)
                    break
                msg_data.append(count_msg)
                vc_data.append(vc_total)

            buf1 = create_dark_chart(labels, msg_data, "Messages serveur (7j)")
            buf2 = create_dark_chart(labels, vc_data, "Vocal serveur (min) (7j)")

            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📊 Statistiques du serveur",
                description="7 derniers jours",
                color=color,
            )
            if buf1:
                embed.set_image(url="attachment://messages.png")
                files = [discord.File(buf1, filename="messages.png")]
                if buf2:
                    files.append(discord.File(buf2, filename="vocal.png"))
                await ctx.send(embed=embed, files=files)
            else:
                embed.add_field(name="Messages/jour", value=", ".join(map(str, msg_data)), inline=False)
                embed.add_field(name="Vocal (min)/jour", value=", ".join(map(str, vc_data)), inline=False)
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.Cog.listener()
    async def on_message(self, message):
        """Track messages par jour"""
        if message.author.bot or not message.guild:
            return
        col = get_collection("message_stats")
        if col is not None:
            try:
                from datetime import datetime, timezone
                today = datetime.now(timezone.utc).date().isoformat()
                await col.update_one(
                    {"guild_id": str(message.guild.id), "user_id": str(message.author.id), "date": today},
                    {"$inc": {"count": 1}},
                    upsert=True
                )
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track temps vocal"""
        if member.bot or not member.guild:
            return
        col = get_collection("voice_sessions")
        if col is not None and before.channel != after.channel:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            today = now.date().isoformat()
            if before.channel:
                # Quit voice - save session duration
                doc = await col.find_one({"guild_id": str(member.guild.id), "user_id": str(member.id), "channel_id": str(before.channel.id)})
                if doc:
                    joined = doc.get("joined", now)
                    if getattr(joined, "tzinfo", None) is None and hasattr(joined, "replace"):
                        joined = joined.replace(tzinfo=timezone.utc)
                    try:
                        dur = (now - joined).total_seconds()
                        dur = max(0, min(dur, 86400))
                    except (TypeError, AttributeError):
                        dur = 60
                    vc_col = get_collection("voice_stats")
                    if vc_col is not None:
                        await vc_col.update_one(
                            {"guild_id": str(member.guild.id), "user_id": str(member.id), "date": today},
                            {"$inc": {"minutes": int(dur / 60)}},
                            upsert=True
                        )
                    await col.delete_one({"_id": doc["_id"]})
            if after.channel:
                await col.insert_one({
                    "guild_id": str(member.guild.id), "user_id": str(member.id),
                    "channel_id": str(after.channel.id), "joined": now,
                })

    @commands.command(name="ranking")
    async def ranking(self, ctx, type_arg: str = "messages"):
        """+ranking messages ou +ranking vocal"""
        try:
            type_arg = type_arg.lower()
            color = await get_guild_color(ctx.guild.id)
            if type_arg == "messages":
                col = get_collection("message_stats")
            else:
                col = get_collection("voice_stats")
            if col is None:
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return
            if type_arg == "messages":
                pipeline = [
                    {"$match": {"guild_id": str(ctx.guild.id)}},
                    {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
                    {"$sort": {"total": -1}},
                    {"$limit": 10}
                ]
                title = "📊 Top 10 Messages"
            else:
                pipeline = [
                    {"$match": {"guild_id": str(ctx.guild.id)}},
                    {"$group": {"_id": "$user_id", "total": {"$sum": "$minutes"}}},
                    {"$sort": {"total": -1}},
                    {"$limit": 10}
                ]
                title = "📊 Top 10 Vocal (min)"
            cursor = col.aggregate(pipeline)
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            max_val = 1
            results = []
            async for doc in cursor:
                results.append((doc["_id"], doc["total"]))
                max_val = max(max_val, doc["total"])
            for i, (uid, total) in enumerate(results):
                user = self.bot.get_user(int(uid))
                name = user.display_name if user else f"User {uid}"
                medal = medals[i] if i < 3 else f"**{i+1}**"
                bar = get_progress_bar(total, max_val, 10)
                unit = "msg" if type_arg == "messages" else "min"
                lines.append(f"{medal} **{name}** {bar} {total} {unit}")
            embed = discord.Embed(
                title=title,
                description="\n".join(lines) if lines else "Aucune donnée",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(StatsCog(bot))
