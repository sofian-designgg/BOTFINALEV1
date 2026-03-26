"""
Cog DM / Annonces
"""
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_config, get_guild_color
from utils.checks import staff_only
try:
    from dmall.sender import send_dm_all  # type: ignore
except ModuleNotFoundError:
    send_dm_all = None


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
    @staff_only()
    @commands.cooldown(1, 600, commands.BucketType.guild)
    async def dmall(self, ctx, *, message: str):
        """Envoie un DM à tous les membres (anti-rate-limit, 3-6s entre chaque)"""
        try:
            if send_dm_all is None:
                return await ctx.send(
                    embed=error_embed(
                        "DM All",
                        "Le module `dmall` est manquant sur l'hébergement.\n"
                        "Installe-le ou supprime la commande `+dmall`.",
                    )
                )
            members = [m for m in ctx.guild.members if not m.bot]
            if not members:
                await ctx.send(embed=error_embed("Erreur", "Aucun membre à contacter."))
                return

            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📢 Confirmation DM All",
                description=f"Vous allez envoyer à **{len(members)}** membres :\n\n{message[:400]}{'...' if len(message) > 400 else ''}",
                color=color,
            )
            embed.add_field(name="🔒 Confirmation", value="Tapez `CONFIRMER` pour valider, ou `annuler` pour annuler.", inline=False)
            embed.add_field(name="⏱️ Anti-rate-limit", value="Délai de 3 à 6 secondes entre chaque DM (évite la détection Discord).", inline=False)
            embed.set_footer(text="Cooldown: 10 min entre chaque utilisation.")
            await ctx.send(embed=embed)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=60)
            except Exception:
                await ctx.send(embed=error_embed("Timeout", "Confirmation annulée (60s)."))
                return

            if msg.content.strip().upper() != "CONFIRMER":
                await ctx.send(embed=error_embed("Annulé", "Envoi annulé."))
                return

            status_msg = await ctx.send("📤 Envoi en cours... (0/" + str(len(members)) + ")")

            async def on_progress(current, total, success, failed, extra):
                try:
                    txt = f"📤 Envoi... ({current}/{total}) ✅ {success} ❌ {failed}"
                    if extra:
                        txt += f"\n{extra}"
                    await status_msg.edit(content=txt)
                except Exception:
                    pass

            success, failed = await send_dm_all(members, message, on_progress)

            embed = success_embed(
                "DM All terminé",
                f"✅ **{success}** membres ont reçu le message\n❌ **{failed}** n'ont pas pu (DMs fermés)\n📊 Total: **{len(members)}**",
                color
            )
            embed.set_footer(text="DMs fermés = membres ayant désactivé les messages du serveur.")
            await status_msg.edit(content=None, embed=embed)
        except commands.CommandOnCooldown as e:
            await ctx.send(embed=error_embed("Cooldown", f"Attendez {int(e.retry_after)} secondes avant de réutiliser."))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="announce")
    @staff_only()
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
    @staff_only()
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
