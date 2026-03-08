"""
Cog DM / Annonces
"""
import asyncio
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
    @commands.cooldown(1, 300, commands.BucketType.guild)
    async def dmall(self, ctx, *, message: str):
        """Envoie un DM à tous les membres (confirmation double, envoi sécurisé)"""
        try:
            members = [m for m in ctx.guild.members if not m.bot]
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📢 Confirmation DM All",
                description=f"Vous allez envoyer à **{len(members)}** membres :\n\n{message[:400]}{'...' if len(message) > 400 else ''}",
                color=color,
            )
            embed.add_field(name="🔒 Sécurité", value="Tapez exactement `CONFIRMER` pour valider, ou `annuler` pour annuler.", inline=False)
            embed.add_field(name="⏱️ Cooldown", value="Une seule utilisation toutes les 5 minutes par serveur.", inline=False)
            embed.set_footer(text="Les DMs sont envoyés avec 2.5s de délai pour éviter le rate limit.")
            await ctx.send(embed=embed)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=60)
            except Exception:
                await ctx.send(embed=error_embed("Timeout", "Confirmation annulée (60s)."))
                return

            if msg.content.strip().upper() != "CONFIRMER":
                await ctx.send(embed=error_embed("Annulé", "Envoi annulé. Tapez `CONFIRMER` pour valider."))
                return

            status_msg = await ctx.send("📤 Envoi en cours... (0/" + str(len(members)) + ")")
            success = 0
            failed = 0
            to_send = message[:2000]

            for i, m in enumerate(members):
                for attempt in range(2):
                    try:
                        dm = m.dm_channel or await m.create_dm()
                        await asyncio.sleep(0.5)
                        await dm.send(to_send)
                        success += 1
                        break
                    except discord.Forbidden:
                        failed += 1
                        break
                    except Exception:
                        if attempt == 0:
                            await asyncio.sleep(5)
                        else:
                            failed += 1
                            break

                await asyncio.sleep(2.5)
                if (i + 1) % 10 == 0 or i + 1 == len(members):
                    try:
                        await status_msg.edit(content=f"📤 Envoi en cours... ({i + 1}/{len(members)}) ✅ {success} | ❌ {failed}")
                    except Exception:
                        pass

            color = await get_guild_color(ctx.guild.id)
            embed = success_embed(
                "DM All terminé",
                f"✅ **{success}** membres ont reçu le message\n❌ **{failed}** n'ont pas pu recevoir (DMs fermés)\n📊 Total: **{len(members)}** membres",
                color
            )
            embed.set_footer(text="Les échecs = membres avec DMs fermés pour les serveurs.")
            await status_msg.edit(content=None, embed=embed)
        except commands.CommandOnCooldown as e:
            await ctx.send(embed=error_embed("Cooldown", f"Attendez {int(e.retry_after)}s avant de réutiliser cette commande."))
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
