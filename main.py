"""
Bot Discord - BOT ALL IN ONE
Main entry point
"""
import os
import discord
from discord.ext import commands
from database import connect_db, close_db, is_connected, get_collection
from utils.guild_config import get_prefix
from utils.checks import can_use_command, CONSULT_COMMANDS
from utils.embeds import error_embed
from config import TOKEN, MONGO_URL, OWNER_ID

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=None,
    owner_id=OWNER_ID if OWNER_ID else None,
)


async def check_license(ctx):
    """Vérifie si le serveur a une licence active (sauf owner et redeem)"""
    if ctx.author.id == ctx.bot.owner_id or ctx.command.name == "redeem":
        return True
    if not ctx.guild:
        return True
    col = get_collection("licenses")
    if col is None:
        return False
    doc = await col.find_one({"guild_id": str(ctx.guild.id), "active": True})
    return doc is not None


@bot.event
async def on_ready():
    """Au démarrage du bot"""
    import time
    from cogs.giveaway_cog import GiveawayButton
    from discord.ui import View
    bot.start_time = getattr(bot, 'start_time', time.time())
    mongo_ok = await is_connected()
    status = "[OK]" if mongo_ok else "[FAIL]"
    view = View(timeout=None)
    view.add_item(GiveawayButton())
    bot.add_view(view)
    print("=" * 50)
    print(f"Bot connecté : {bot.user.name}#{bot.user.discriminator}")
    print(f"MongoDB : {status} {'Connecté' if mongo_ok else 'Déconnecté'}")
    print("=" * 50)


@bot.event
async def on_command_error(ctx, error):
    """Messages clairs pour CheckFailure (ex. staff_only) sans doublon avec before_invoke."""
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(
            embed=error_embed("Cooldown", f"Réessaie dans {error.retry_after:.1f}s.")
        )
    orig = error.original if isinstance(error, commands.CommandInvokeError) else error
    if isinstance(orig, commands.CheckFailure):
        msg = str(orig)
        if msg in ("No license", "Staff only"):
            return
        await ctx.send(embed=error_embed("Commande impossible", msg))
        return


@bot.before_invoke
async def before_command(ctx):
    """Vérification avant chaque commande"""
    if not ctx.command:
        return
    if ctx.command.name in ("redeem", "help"):
        return
    if ctx.guild:
        # Vérification licence
        has_license = await check_license(ctx)
        if not has_license:
            from utils.embeds import error_embed
            embed = error_embed(
                "Licence requise",
                "Ce serveur n'a pas de licence active.\nUtilisez `+redeem [code]` pour activer le bot."
            )
            await ctx.send(embed=embed)
            raise commands.CheckFailure("No license")
        # Restriction : seuls consultation + invites pour les non-staff
        cmd_key = ctx.command.qualified_name
        allowed, err_msg = await can_use_command(ctx, cmd_key)
        if not allowed:
            from utils.embeds import error_embed
            embed = error_embed("Accès refusé", err_msg)
            await ctx.send(embed=embed)
            raise commands.CheckFailure("Staff only")


async def load_extensions():
    """Charge tous les cogs"""
    cogs = [
        "cogs.config_cog",
        "cogs.help_cog",
        "cogs.detail_cog",
        "cogs.database_cog",
        "cogs.moderation_cog",
        "cogs.xp_cog",
        "cogs.minigames_cog",
        "cogs.stats_cog",
        "cogs.economy_cog",
        "cogs.shop_cog",
        "cogs.license_cog",
        "cogs.announcements_cog",
        "cogs.giveaway_cog",
        "cogs.fame_cog",
        "cogs.streaks_cog",
        "cogs.invites_cog",
        "cogs.welcome_cog",
        "cogs.voice_roles_cog",
        "cogs.casino_cog",
    ]
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            print(f"  [OK] {cog}")
        except Exception as e:
            print(f"  [FAIL] {cog}: {e}")


async def main():
    """Point d'entrée principal"""
    mongo_ok = await connect_db()
    if not mongo_ok:
        print("⚠️ MongoDB non connecté - Certaines fonctionnalités seront limitées")

    await load_extensions()
    await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(close_db())
