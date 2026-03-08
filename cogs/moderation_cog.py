"""
Cog Modération complète
"""
import re
import discord
from discord.ext import commands
from discord import app_commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color

# Parsing durée: 1m, 1h, 1d
def parse_duration(s: str) -> int:
    s = s.lower().strip()
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    total = 0
    parts = re.findall(r"(\d+)([smhd])", s)
    for num, unit in parts:
        total += int(num) * multipliers.get(unit, 1)
    if not parts and s.isdigit():
        total = int(s)
    return total


async def send_mod_log(bot, guild_id: int, embed: discord.Embed):
    config = await get_guild_config(guild_id)
    channel_id = config.get("log_channel_id")
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except Exception:
            pass


class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    def _has_mod(self, ctx):
        return ctx.author.guild_permissions.ban_members or ctx.author.guild_permissions.kick_members

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = "Aucune raison"):
        """Bannit un membre"""
        try:
            if member.top_role >= ctx.author.top_role:
                await ctx.send(embed=error_embed("Erreur", "Vous ne pouvez pas bannir ce membre."))
                return
            await member.ban(reason=reason)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Bannissement", f"**{member}** a été banni. Raison: {reason}", color))

            log_embed = discord.Embed(title="🔨 Bannissement", color=0xED4245)
            log_embed.add_field(name="Membre", value=str(member), inline=True)
            log_embed.add_field(name="Par", value=str(ctx.author), inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            await send_mod_log(self.bot, ctx.guild.id, log_embed)

            col = get_collection("mod_logs")
            if col:
                await col.insert_one({"type": "ban", "guild_id": str(ctx.guild.id), "user_id": str(member.id), "mod_id": str(ctx.author.id), "reason": reason})
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int, *, reason: str = "Aucune raison"):
        """Débannit un utilisateur par ID"""
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Débannissement", f"**{user}** a été débanni.", color))

            log_embed = discord.Embed(title="✅ Débannissement", color=0x57F287)
            log_embed.add_field(name="Utilisateur", value=str(user), inline=True)
            log_embed.add_field(name="Par", value=str(ctx.author), inline=True)
            await send_mod_log(self.bot, ctx.guild.id, log_embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "Aucune raison"):
        """Expulse un membre"""
        try:
            if member.top_role >= ctx.author.top_role:
                await ctx.send(embed=error_embed("Erreur", "Vous ne pouvez pas expulser ce membre."))
                return
            await member.kick(reason=reason)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Expulsion", f"**{member}** a été expulsé. Raison: {reason}", color))

            log_embed = discord.Embed(title="👢 Expulsion", color=0xFEE75C)
            log_embed.add_field(name="Membre", value=str(member), inline=True)
            log_embed.add_field(name="Par", value=str(ctx.author), inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            await send_mod_log(self.bot, ctx.guild.id, log_embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison"):
        """Mute un membre (rôle mute)"""
        try:
            config = await get_guild_config(ctx.guild.id)
            mute_role_id = config.get("mute_role_id")
            if not mute_role_id:
                mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
                if not mute_role:
                    mute_role = await ctx.guild.create_role(name="Muted", permissions=discord.Permissions(0))
                mute_role_id = mute_role.id
                from utils.guild_config import update_guild_config
                await update_guild_config(ctx.guild.id, {"mute_role_id": mute_role_id})

            mute_role = ctx.guild.get_role(mute_role_id)
            if not mute_role:
                await ctx.send(embed=error_embed("Erreur", "Rôle mute introuvable."))
                return

            await member.add_roles(mute_role, reason=reason)
            secs = parse_duration(duration)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Mute", f"**{member}** a été mute pour {duration}. Raison: {reason}", color))

            log_embed = discord.Embed(title="🔇 Mute", color=0x95A5A6)
            log_embed.add_field(name="Membre", value=str(member), inline=True)
            log_embed.add_field(name="Par", value=str(ctx.author), inline=True)
            log_embed.add_field(name="Durée", value=duration, inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            await send_mod_log(self.bot, ctx.guild.id, log_embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member):
        """Retire le mute"""
        try:
            config = await get_guild_config(ctx.guild.id)
            mute_role_id = config.get("mute_role_id")
            mute_role = ctx.guild.get_role(mute_role_id) if mute_role_id else discord.utils.get(ctx.guild.roles, name="Muted")
            if mute_role and mute_role in member.roles:
                await member.remove_roles(mute_role)
                color = await get_guild_color(ctx.guild.id)
                await ctx.send(embed=success_embed("Unmute", f"**{member}** n'est plus mute.", color))
            else:
                await ctx.send(embed=error_embed("Erreur", "Ce membre n'est pas mute."))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="timeout")
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison"):
        """Timeout Discord natif"""
        try:
            secs = parse_duration(duration)
            secs = min(secs, 2419200)  # max 28 jours
            import datetime
            until = discord.utils.utcnow() + datetime.timedelta(seconds=secs)
            await member.timeout(until, reason=reason)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Timeout", f"**{member}** a reçu un timeout de {duration}.", color))

            log_embed = discord.Embed(title="⏱️ Timeout", color=0xFEE75C)
            log_embed.add_field(name="Membre", value=str(member), inline=True)
            log_embed.add_field(name="Par", value=str(ctx.author), inline=True)
            log_embed.add_field(name="Durée", value=duration, inline=True)
            await send_mod_log(self.bot, ctx.guild.id, log_embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="untimeout")
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        """Retire le timeout"""
        try:
            await member.timeout(None)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Timeout", f"**{member}** n'est plus en timeout.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "Aucune raison"):
        """Avertit un membre"""
        try:
            col = get_collection("warnings")
            await col.insert_one({
                "guild_id": str(ctx.guild.id),
                "user_id": str(member.id),
                "mod_id": str(ctx.author.id),
                "reason": reason,
            })
            count = await col.count_documents({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Avertissement", f"**{member}** a été averti ({count} avertissement(s)). Raison: {reason}", color))

            log_embed = discord.Embed(title="⚠️ Avertissement", color=0xFEE75C)
            log_embed.add_field(name="Membre", value=str(member), inline=True)
            log_embed.add_field(name="Par", value=str(ctx.author), inline=True)
            log_embed.add_field(name="Total", value=str(count), inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            await send_mod_log(self.bot, ctx.guild.id, log_embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="warnings")
    @commands.has_permissions(moderate_members=True)
    async def warnings_cmd(self, ctx, member: discord.Member):
        """Liste les avertissements d'un membre"""
        try:
            col = get_collection("warnings")
            cursor = col.find({"guild_id": str(ctx.guild.id), "user_id": str(member.id)}).sort("_id", -1).limit(10)
            warns = []
            async for w in cursor:
                warns.append(f"• {w.get('reason', 'N/A')} (par <@{w.get('mod_id')}>)")
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title=f"⚠️ Avertissements de {member}",
                description="\n".join(warns) if warns else "Aucun avertissement",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="clearwarns")
    @commands.has_permissions(moderate_members=True)
    async def clearwarns(self, ctx, member: discord.Member):
        """Efface tous les avertissements d'un membre"""
        try:
            col = get_collection("warnings")
            result = await col.delete_many({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Avertissements", f"{result.deleted_count} avertissement(s) effacés pour **{member}**.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="purge")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        """Supprime des messages"""
        try:
            amount = min(amount, 100)
            deleted = await ctx.channel.purge(limit=amount + 1)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Purge", f"{len(deleted)-1} message(s) supprimé(s).", color), delete_after=5)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int):
        """Définit le slowmode du salon"""
        try:
            seconds = max(0, min(seconds, 21600))
            await ctx.channel.edit(slowmode_delay=seconds)
            color = await get_guild_color(ctx.guild.id)
            msg = f"Slowmode désactivé" if seconds == 0 else f"Slowmode: {seconds}s"
            await ctx.send(embed=success_embed("Slowmode", msg, color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        """Verrouille le salon actuel"""
        try:
            await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Lock", "Salon verrouillé 🔒", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        """Déverrouille le salon actuel"""
        try:
            await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Unlock", "Salon déverrouillé 🔓", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="lockdown")
    @commands.has_permissions(administrator=True)
    async def lockdown(self, ctx):
        """Verrouille tous les salons textuels"""
        try:
            count = 0
            for ch in ctx.guild.text_channels:
                try:
                    await ch.set_permissions(ctx.guild.default_role, send_messages=False)
                    count += 1
                except Exception:
                    pass
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Lockdown", f"{count} salon(s) verrouillé(s) 🔒", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="unlockdown")
    @commands.has_permissions(administrator=True)
    async def unlockdown(self, ctx):
        """Déverrouille tous les salons"""
        try:
            count = 0
            for ch in ctx.guild.text_channels:
                try:
                    await ch.set_permissions(ctx.guild.default_role, send_messages=None)
                    count += 1
                except Exception:
                    pass
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Unlockdown", f"{count} salon(s) déverrouillé(s) 🔓", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.group(name="role")
    @commands.has_permissions(manage_roles=True)
    async def role_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @role_group.command(name="add")
    async def role_add(self, ctx, member: discord.Member, role: discord.Role):
        try:
            await member.add_roles(role)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Rôle", f"Rôle {role.mention} ajouté à **{member}**.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @role_group.command(name="remove")
    async def role_remove(self, ctx, member: discord.Member, role: discord.Role):
        try:
            await member.remove_roles(role)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Rôle", f"Rôle {role.mention} retiré de **{member}**.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="nick")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str = None):
        """Change le surnom d'un membre"""
        try:
            await member.edit(nick=nickname[:32] if nickname else None)
            color = await get_guild_color(ctx.guild.id)
            msg = f"Surnom de **{member}** : **{nickname}**" if nickname else f"Surnom de **{member}** réinitialisé."
            await ctx.send(embed=success_embed("Surnom", msg, color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    # Auto-mod : mots bannis
    @commands.command(name="addword")
    @commands.has_permissions(manage_guild=True)
    async def addword(self, ctx, *, word: str):
        """Ajoute un mot banni"""
        try:
            col = get_collection("banned_words")
            word = word.lower().strip()
            await col.update_one(
                {"guild_id": str(ctx.guild.id)},
                {"$addToSet": {"words": word}},
                upsert=True
            )
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Mot banni", f"`{word}` ajouté à la liste.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="removeword")
    @commands.has_permissions(manage_guild=True)
    async def removeword(self, ctx, *, word: str):
        """Retire un mot banni"""
        try:
            col = get_collection("banned_words")
            word = word.lower().strip()
            await col.update_one(
                {"guild_id": str(ctx.guild.id)},
                {"$pull": {"words": word}}
            )
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Mot banni", f"`{word}` retiré de la liste.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="wordlist")
    @commands.has_permissions(manage_guild=True)
    async def wordlist(self, ctx):
        """Liste les mots bannis"""
        try:
            col = get_collection("banned_words")
            doc = await col.find_one({"guild_id": str(ctx.guild.id)})
            words = doc.get("words", []) if doc else []
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📝 Mots bannis",
                description=", ".join(f"`{w}`" for w in words[:30]) if words else "Aucun mot banni",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.Cog.listener()
    async def on_message(self, message):
        """Auto-mod: anti-spam, anti-liens, mots bannis"""
        if message.author.bot or not message.guild:
            return
        config = await get_guild_config(message.guild.id)
        automod = config.get("automod", {})
        # On peut étendre l'auto-mod plus tard avec des configs
        col = get_collection("banned_words")
        doc = await col.find_one({"guild_id": str(message.guild.id)}) if col else None
        words = doc.get("words", []) if doc else []
        content = message.content.lower()
        for w in words:
            if w in content:
                try:
                    await message.delete()
                    await message.channel.send(embed=error_embed("Message supprimé", f"Mot banni détecté. {message.author.mention}"), delete_after=5)
                except Exception:
                    pass
                break


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
