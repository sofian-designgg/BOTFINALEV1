"""
Cog Économie - Monnaie personnalisable
"""
import random
import discord
from discord.ext import commands
from discord import app_commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color

DAILY_AMOUNT = 500
DAILY_STREAK_BONUS = 50
WEEKLY_AMOUNT = 2500


async def get_balance(guild_id: int, user_id: int) -> int:
    col = get_collection("economy")
    doc = await col.find_one({"guild_id": str(guild_id), "user_id": str(user_id)})
    return doc.get("balance", 0) if doc else 0


async def add_coins(guild_id: int, user_id: int, amount: int):
    col = get_collection("economy")
    await col.update_one(
        {"guild_id": str(guild_id), "user_id": str(user_id)},
        {"$inc": {"balance": amount}},
        upsert=True
    )


async def remove_coins(guild_id: int, user_id: int, amount: int) -> bool:
    balance = await get_balance(guild_id, user_id)
    if balance < amount:
        return False
    col = get_collection("economy")
    await col.update_one(
        {"guild_id": str(guild_id), "user_id": str(user_id)},
        {"$inc": {"balance": -amount}}
    )
    return True


class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="balance")
    async def balance(self, ctx, member: discord.Member = None):
        """Affiche le solde (monnaie configurée)"""
        try:
            member = member or ctx.author
            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            currency_emoji = config.get("currency_emoji", "💰")

            bal = await get_balance(ctx.guild.id, member.id)
            color = await get_guild_color(ctx.guild.id)

            embed = discord.Embed(
                title=f"{currency_emoji} Solde de {member.display_name}",
                description=f"**{bal:,}** {currency_name}",
                color=color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text="━━━━━━━━━━━━━━━━━━━━")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="balanceembed")
    async def balanceembed(self, ctx):
        """Poste un embed avec bouton pour afficher son solde."""
        try:
            config = await get_guild_config(ctx.guild.id)
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)

            v = discord.ui.View(timeout=None)
            btn = discord.ui.Button(
                label="Afficher mon compte bancaire",
                style=discord.ButtonStyle.success,
                custom_id="bank:show",
            )

            async def cb(interaction: discord.Interaction):
                if not interaction.guild:
                    return
                bal = await get_balance(interaction.guild.id, interaction.user.id)
                conf = await get_guild_config(interaction.guild.id)
                currency_name = conf.get("currency_name", "SayuCoins")
                currency_emoji2 = conf.get("currency_emoji", "💰")
                emb = discord.Embed(
                    title=f"{currency_emoji2} Ton compte bancaire",
                    description=f"**{bal:,}** {currency_name}",
                    color=await get_guild_color(interaction.guild.id),
                )
                await interaction.response.send_message(embed=emb, ephemeral=True)

            btn.callback = cb
            v.add_item(btn)
            await ctx.send(
                embed=discord.Embed(
                    title=f"{currency_emoji} Banque",
                    description="Clique sur le bouton pour afficher ton solde en privé.",
                    color=color,
                ),
                view=v,
            )
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

class BankPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = discord.ui.Button(
            label="Afficher mon compte bancaire",
            style=discord.ButtonStyle.success,
            custom_id="bank:show",
        )

        async def cb(interaction: discord.Interaction):
            if not interaction.guild:
                return
            bal = await get_balance(interaction.guild.id, interaction.user.id)
            conf = await get_guild_config(interaction.guild.id)
            currency_name = conf.get("currency_name", "SayuCoins")
            currency_emoji2 = conf.get("currency_emoji", "💰")
            emb = discord.Embed(
                title=f"{currency_emoji2} Ton compte bancaire",
                description=f"**{bal:,}** {currency_name}",
                color=await get_guild_color(interaction.guild.id),
            )
            await interaction.response.send_message(embed=emb, ephemeral=True)

        btn.callback = cb
        self.add_item(btn)

    @commands.command(name="daily")
    async def daily(self, ctx):
        """Récompense quotidienne avec streak bonus"""
        try:
            col = get_collection("economy")
            col_daily = get_collection("daily_streaks")
            doc = await col_daily.find_one({"guild_id": str(ctx.guild.id), "user_id": str(ctx.author.id)})
            from discord.utils import utcnow
            now = utcnow()
            # Normalise datetimes (Mongo peut contenir du naive)
            if getattr(now, "tzinfo", None) is None:
                from datetime import timezone
                now = now.replace(tzinfo=timezone.utc)

            if doc:
                last = doc.get("last_daily")
                if last:
                    from datetime import timezone
                    last_dt = last
                    if getattr(last_dt, "tzinfo", None) is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    now_dt = now
                    diff = (now_dt - last_dt).total_seconds()
                    streak = doc.get("streak", 0)
                    if diff < 86400:  # pas encore 24h
                        secs_left = 86400 - diff
                        h = int(secs_left // 3600)
                        m = int((secs_left % 3600) // 60)
                        await ctx.send(embed=error_embed("Daily", f"Prochaine récompense dans {h}h{m}m"))
                        return
                    if diff > 172800:  # plus de 48h -> reset streak
                        streak = 0
                    streak += 1
                else:
                    streak = 1
            else:
                streak = 1

            amount = DAILY_AMOUNT + (streak - 1) * DAILY_STREAK_BONUS
            await add_coins(ctx.guild.id, ctx.author.id, amount)
            await col_daily.update_one(
                {"guild_id": str(ctx.guild.id), "user_id": str(ctx.author.id)},
                {"$set": {"last_daily": now, "streak": streak}},
                upsert=True
            )

            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)

            embed = success_embed(
                "Récompense quotidienne",
                f"+**{amount:,}** {currency_name} {currency_emoji}\nStreak: **{streak}** jours",
                color
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="weekly")
    async def weekly(self, ctx):
        """Récompense hebdomadaire"""
        try:
            col = get_collection("economy")
            col_weekly = get_collection("weekly_cooldowns")
            doc = await col_weekly.find_one({"guild_id": str(ctx.guild.id), "user_id": str(ctx.author.id)})
            from discord.utils import utcnow
            now = utcnow()
            if getattr(now, "tzinfo", None) is None:
                from datetime import timezone
                now = now.replace(tzinfo=timezone.utc)

            if doc and doc.get("last_weekly"):
                from datetime import timezone
                last = doc["last_weekly"]
                if getattr(last, "tzinfo", None) is None:
                    last = last.replace(tzinfo=timezone.utc)
                diff = (now - last).total_seconds()
                if diff < 604800:  # 7 jours
                    secs_left = 604800 - diff
                    d = int(secs_left // 86400)
                    await ctx.send(embed=error_embed("Weekly", f"Prochaine récompense dans {d} jours"))
                    return

            await add_coins(ctx.guild.id, ctx.author.id, WEEKLY_AMOUNT)
            await col_weekly.update_one(
                {"guild_id": str(ctx.guild.id), "user_id": str(ctx.author.id)},
                {"$set": {"last_weekly": now}},
                upsert=True
            )

            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)

            embed = success_embed(
                "Récompense hebdomadaire",
                f"+**{WEEKLY_AMOUNT:,}** {currency_name} {currency_emoji}",
                color
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="pay")
    async def pay(self, ctx, member: discord.Member, amount: int):
        """Transfère de la monnaie à un membre"""
        try:
            if member.bot:
                await ctx.send(embed=error_embed("Erreur", "Impossible de payer un bot."))
                return
            if member.id == ctx.author.id:
                await ctx.send(embed=error_embed("Erreur", "Vous ne pouvez pas vous payer vous-même."))
                return
            if amount < 1:
                await ctx.send(embed=error_embed("Erreur", "Montant invalide."))
                return

            success = await remove_coins(ctx.guild.id, ctx.author.id, amount)
            if not success:
                bal = await get_balance(ctx.guild.id, ctx.author.id)
                await ctx.send(embed=error_embed("Solde insuffisant", f"Vous avez **{bal:,}**."))
                return

            await add_coins(ctx.guild.id, member.id, amount)
            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)

            embed = success_embed(
                "Transfert",
                f"**{amount:,}** {currency_name} {currency_emoji} envoyés à **{member}**.",
                color
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="addcoins")
    @commands.has_permissions(administrator=True)
    async def addcoins(self, ctx, member: discord.Member, amount: int):
        """Ajoute de la monnaie (admin)"""
        try:
            amount = max(0, amount)
            await add_coins(ctx.guild.id, member.id, amount)
            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Coins", f"+{amount:,} {currency_name} pour **{member}**.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="addallcoins")
    @commands.has_permissions(administrator=True)
    async def addallcoins(self, ctx, amount: int):
        """Ajoute des SayuCoins à tous les membres (admin)"""
        try:
            amount = int(amount)
            if amount < 1:
                await ctx.send(embed=error_embed("Coins", "Montant invalide."))
                return
            col = get_collection("economy")
            if col is None:
                await ctx.send(embed=error_embed("DB", "Erreur collection."))
                return
            n = 0
            for m in ctx.guild.members:
                if m.bot:
                    continue
                await col.update_one(
                    {"guild_id": str(ctx.guild.id), "user_id": str(m.id)},
                    {"$inc": {"balance": amount}},
                    upsert=True,
                )
                n += 1
            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(
                embed=success_embed(
                    "Coins",
                    f"+**{amount:,}** {currency_name} {currency_emoji} pour **{n}** membres.",
                    color,
                )
            )
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="coinstop")
    async def coinstop(self, ctx, page: int = 1):
        """Top 10 richesse (leaderboard coins)"""
        try:
            col = get_collection("economy")
            cursor = col.find({"guild_id": str(ctx.guild.id)}).sort("balance", -1).skip((page - 1) * 10).limit(10)
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)
            idx = 0
            async for doc in cursor:
                user = self.bot.get_user(int(doc["user_id"]))
                name = user.display_name if user else f"User {doc['user_id']}"
                bal = doc.get("balance", 0)
                medal = medals[idx] if idx < 3 else f"**{idx + 1}**"
                lines.append(f"{medal} **{name}** — {bal:,} {currency_emoji}")
                idx += 1
            embed = discord.Embed(
                title=f"💰 Classement richesse",
                description="\n".join(lines) if lines else "Aucune donnée",
                color=color,
            )
            embed.set_footer(text=f"Page {page} • +coinstop [page]")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="removecoins")
    @commands.has_permissions(administrator=True)
    async def removecoins(self, ctx, member: discord.Member, amount: int):
        """Retire de la monnaie (admin)"""
        try:
            amount = max(0, amount)
            success = await remove_coins(ctx.guild.id, member.id, amount)
            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            color = await get_guild_color(ctx.guild.id)
            if success:
                await ctx.send(embed=success_embed("Coins", f"-{amount:,} {currency_name} pour **{member}**.", color))
            else:
                await ctx.send(embed=error_embed("Erreur", "Solde insuffisant."))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(EconomyCog(bot))
    bot.add_view(BankPanelView())
