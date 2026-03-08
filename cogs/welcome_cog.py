"""
Cog Welcome / Leave messages
"""
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.guild_config import get_guild_config


class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot or not member.guild:
            return
        try:
            config = await get_guild_config(member.guild.id)
            channel_id = config.get("welcome_channel_id")
            if not channel_id:
                return
            channel = member.guild.get_channel(channel_id)
            if not channel:
                return
            msg = config.get("welcome_msg", "Bienvenue {user} sur **{server}** ! 👋")
            msg = msg.replace("{user}", member.mention).replace("{server}", member.guild.name)
            from utils.guild_config import get_guild_color
            color_val = await get_guild_color(member.guild.id)
            embed = discord.Embed(description=msg, color=color_val)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.bot or not member.guild:
            return
        try:
            config = await get_guild_config(member.guild.id)
            channel_id = config.get("welcome_channel_id")  # ou leave_channel si séparé - on réutilise welcome
            if not channel_id:
                return
            channel = member.guild.get_channel(channel_id)
            if not channel:
                return
            msg = config.get("leave_msg", "{user} a quitté le serveur. 👋")
            msg = msg.replace("{user}", str(member)).replace("{server}", member.guild.name)
            from utils.guild_config import get_guild_color
            color = await get_guild_color(member.guild.id)
            embed = discord.Embed(description=msg, color=color)
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
