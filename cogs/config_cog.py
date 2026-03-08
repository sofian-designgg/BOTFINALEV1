"""
Cog Personnalisation - Configuration complète par serveur
"""
import discord
from discord.ext import commands
from discord import app_commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, info_embed, separator
from utils.guild_config import get_guild_config, update_guild_config, get_guild_color, DEFAULT_GUILD_CONFIG


def hex_to_int(hex_str: str) -> int:
    """Convertit #RRGGBB en int"""
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 6 and all(c in "0123456789abcdefABCDEF" for c in hex_str):
        return int(hex_str, 16)
    return 0x5865F2


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("Base de données", "MongoDB est déconnecté."))
            return False
        return True

    @commands.command(name="setcolor")
    async def setcolor(self, ctx, hex_color: str):
        """Définit la couleur principale des embeds"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            color = hex_to_int(hex_color)
            await update_guild_config(ctx.guild.id, {"color": color})
            embed = success_embed("Couleur mise à jour", f"Nouvelle couleur : `#{color:06X}`", color)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setbotname")
    async def setbotname(self, ctx, *, name: str):
        """Change le surnom du bot sur le serveur"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await ctx.guild.me.edit(nick=name[:32])
            await ctx.send(embed=success_embed("Surnom", f"Le bot s'appelle maintenant **{name}**", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setprefix")
    async def setprefix(self, ctx, prefix: str):
        """Change le préfixe du bot"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            prefix = prefix[:5].strip() or "+"
            await update_guild_config(ctx.guild.id, {"prefix": prefix})
            await ctx.send(embed=success_embed("Préfixe", f"Nouveau préfixe : `{prefix}`", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setcurrency")
    async def setcurrency(self, ctx, name: str, emoji: str = "💰"):
        """Renomme la monnaie (ex: SayuCoins GoldCoins 🪙)"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"currency_name": name, "currency_emoji": emoji})
            await ctx.send(embed=success_embed("Monnaie", f"Nouvelle monnaie : **{name}** {emoji}", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setxpname")
    async def setxpname(self, ctx, *, name: str):
        """Renomme le système XP"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"xp_name": name})
            await ctx.send(embed=success_embed("XP", f"Nom du système XP : **{name}**", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setlevelupmsg")
    async def setlevelupmsg(self, ctx, *, message: str):
        """Personnalise le message de level-up ({user}, {level})"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"level_up_msg": message})
            await ctx.send(embed=success_embed("Message level-up", "Message mis à jour.", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setlogchannel")
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Définit le salon des logs de modération"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"log_channel_id": channel.id})
            await ctx.send(embed=success_embed("Logs", f"Salon des logs : {channel.mention}", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setwelcomechannel")
    async def setwelcomechannel(self, ctx, channel: discord.TextChannel):
        """Définit le salon de bienvenue"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"welcome_channel_id": channel.id})
            await ctx.send(embed=success_embed("Bienvenue", f"Salon : {channel.mention}", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setwelcomemsg")
    async def setwelcomemsg(self, ctx, *, message: str):
        """Message de bienvenue personnalisé ({user}, {server})"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"welcome_msg": message})
            await ctx.send(embed=success_embed("Message bienvenue", "Message mis à jour.", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setleavemsg")
    async def setleavemsg(self, ctx, *, message: str):
        """Message de départ personnalisé"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"leave_msg": message})
            await ctx.send(embed=success_embed("Message départ", "Message mis à jour.", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setmuterole")
    async def setmuterole(self, ctx, role: discord.Role):
        """Définit le rôle mute"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"mute_role_id": role.id})
            await ctx.send(embed=success_embed("Rôle mute", f"Rôle : {role.mention}", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setadminrole")
    async def setadminrole(self, ctx, role: discord.Role):
        """Définit le rôle admin du bot"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"admin_role_id": role.id})
            await ctx.send(embed=success_embed("Rôle admin", f"Rôle : {role.mention}", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="setshopname")
    async def setshopname(self, ctx, *, name: str):
        """Renomme le shop"""
        try:
            if not ctx.author.guild_permissions.administrator:
                await ctx.send(embed=error_embed("Permissions", "Administrateur requis."))
                return
            await update_guild_config(ctx.guild.id, {"shop_name": name})
            await ctx.send(embed=success_embed("Shop", f"Nom du shop : **{name}**", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="settings")
    async def settings(self, ctx):
        """Affiche tous les paramètres du serveur"""
        try:
            config = await get_guild_config(ctx.guild.id)
            color = await get_guild_color(ctx.guild.id)

            embed = discord.Embed(
                title="⚙️ Paramètres du serveur",
                color=color,
            )
            embed.add_field(name="Préfixe", value=f"`{config.get('prefix', '+')}`", inline=True)
            embed.add_field(name="Couleur", value=f"`#{config.get('color', 0x5865F2):06X}`" if isinstance(config.get('color'), int) else f"`{config.get('color')}`", inline=True)
            embed.add_field(name="Monnaie", value=f"{config.get('currency_emoji')} {config.get('currency_name')}", inline=True)
            embed.add_field(name="Nom XP", value=config.get('xp_name', 'XP'), inline=True)
            embed.add_field(name="Shop", value=config.get('shop_name', 'Sayuri Shop'), inline=True)
            embed.add_field(name="Logs", value=f"<#{config.get('log_channel_id')}>" if config.get('log_channel_id') else "Non défini", inline=True)
            embed.add_field(name="Bienvenue", value=f"<#{config.get('welcome_channel_id')}>" if config.get('welcome_channel_id') else "Non défini", inline=True)
            embed.add_field(name="Mute role", value=f"<@&{config.get('mute_role_id')}>" if config.get('mute_role_id') else "Non défini", inline=True)
            embed.add_field(name="Admin role", value=f"<@&{config.get('admin_role_id')}>" if config.get('admin_role_id') else "Non défini", inline=True)
            embed.set_footer(text=separator())

            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="resetconfig")
    async def resetconfig(self, ctx):
        """Remet tous les paramètres par défaut (propriétaire serveur)"""
        try:
            if ctx.author.id != ctx.guild.owner_id:
                await ctx.send(embed=error_embed("Permissions", "Seul le propriétaire du serveur peut réinitialiser."))
                return
            await update_guild_config(ctx.guild.id, DEFAULT_GUILD_CONFIG)
            await ctx.send(embed=success_embed("Réinitialisation", "Tous les paramètres ont été remis par défaut.", await get_guild_color(ctx.guild.id)))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
