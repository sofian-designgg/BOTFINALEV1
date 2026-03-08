"""
Cog DM / Annonces
"""
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_config, get_guild_color


class AnnouncementsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="dmall")
    @commands.has_permissions(administrator=True)
    async def dmall(self, ctx, *, message: str):
        """Envoie un DM à tous les membres (confirmation avant envoi)"""
        try:
            members = [m for m in ctx.guild.members if not m.bot]
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📢 Confirmation DM All",
                description=f"Vous allez envoyer ce message à **{len(members)}** membres :\n\n{message[:500]}{'...' if len(message) > 500 else ''}",
                color=color,
            )
            embed.add_field(name="Approuvez", value="Répondez `oui` pour confirmer, `non` pour annuler.", inline=False)
            await ctx.send(embed=embed)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=30)
            except Exception:
                await ctx.send(embed=error_embed("Timeout", "Confirmation annulée."))
                return

            if msg.content.lower() not in ("oui", "yes", "o", "y"):
                await ctx.send(embed=error_embed("Annulé", "Envoi annulé."))
                return

            success = 0
            failed = 0
            for m in members:
                try:
                    dm = m.dm_channel or await m.create_dm()
                    await dm.send(message[:2000])
                    success += 1
                except Exception:
                    failed += 1

            color = await get_guild_color(ctx.guild.id)
            embed = success_embed(
                "DM All terminé",
                f"✅ Succès: **{success}**\n❌ Échecs: **{failed}**\n📊 Total: **{success + failed}**",
                color
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="announce")
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx, channel: discord.TextChannel, *, message: str):
        """Annonce stylisée dans un salon"""
        try:
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📢 Annonce",
                description=message,
                color=color,
            )
            embed.set_footer(text=f"Par {ctx.author}")
            embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
            await channel.send(embed=embed)
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Annonce", f"Annonce envoyée dans {channel.mention}.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="embed")
    @commands.has_permissions(administrator=True)
    async def embed_cmd(self, ctx, *, text: str):
        """+embed [titre] | [description] — Crée un embed personnalisé"""
        try:
            parts = text.split("|", 1)
            title = parts[0].strip() if parts else "Embed"
            description = parts[1].strip() if len(parts) > 1 else ""
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(title=title, description=description, color=color)
            await ctx.send(embed=embed)
            try:
                await ctx.message.delete()
            except Exception:
                pass
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(AnnouncementsCog(bot))
