"""
Vérifications de permissions
"""
import discord
from discord.ext import commands

from utils.guild_config import get_guild_config


# Commandes que TOUT LE MONDE peut utiliser (consultation + invites uniquement)
CONSULT_COMMANDS = {
    # Stats & consultation
    "rank", "leaderboard", "balance", "coinstop",
    "stats", "serverstats", "ranking",
    "fame", "fameleaderboard", "streak", "streakleaderboard",
    "invites", "inviteleaderboard", "mylink", "createinvite",
    "voiceprogress", "vocalprogress", "vp",
    "help", "aide", "commandes", "cmds",
    "detail", "detailed", "aidecommande", "man",
    "listmessageroles", "listvoiceroles",
    "helpcasino", "casinohelp", "aidecasino",
    "helpcasinocomplet", "casinolist", "listecasino",
    "casinoconfig", "casinolb", "casinoleaderboard",
    "casinostats", "casino", "trade", "tradecancel", "sellrole", "auctioncancel", "auctionbuyout",
    "casino slots", "casino flip", "casino pfc", "casino blackjack",
    "casinoranks", "casinoranks me",
    "hierarchie",
    "balanceembed", "rankembed", "statsembed",
    "rankcasinoembed",
    "shop", "inventory", "glist",
    # Récompenses (non-staff)
    "daily", "weekly",
    "settings", "ping", "licenceinfo", "redeem",
    # Modération view only
    "warnings",
}


async def is_staff(ctx) -> bool:
    """
    Vérifie si l'utilisateur est staff (admin Discord OU rôle admin configuré).
    Les commandes de modération ont déjà leurs propres checks (ban_members, etc.)
    """
    if not ctx.guild:
        return True
    if ctx.author.guild_permissions.administrator:
        return True
    config = (await get_guild_config(ctx.guild.id)) or {}
    admin_role_id = config.get("admin_role_id")
    try:
        admin_role_id = int(admin_role_id) if admin_role_id is not None else None
    except (TypeError, ValueError):
        admin_role_id = None
    if admin_role_id and any(r.id == admin_role_id for r in ctx.author.roles):
        return True
    return False


async def can_use_command(ctx, command_name: str) -> tuple[bool, str]:
    """
    Vérifie si l'utilisateur peut utiliser la commande.
    Retourne (autorisé, message_erreur).
    """
    # Propriétaire du bot = accès total
    if ctx.author.id == ctx.bot.owner_id:
        return True, ""
    # Les commandes de consultation sont autorisées pour tous
    if command_name in CONSULT_COMMANDS:
        return True, ""
    # Staff (admin ou rôle admin) peut tout utiliser
    if await is_staff(ctx):
        return True, ""
    # Sinon refusé
    return False, "Cette commande est réservée au staff. Seules la consultation (stats, rank, invites, shop...) est autorisée pour tous."


def staff_only():
    """
    Commandes réservées au staff : aligné sur `can_use_command` / `is_staff`
    (administrateur Discord **ou** rôle admin configuré avec `+setadminrole`),
    ainsi que le propriétaire du bot.
    Remplace `@commands.has_permissions(administrator=True)` qui ignorait le rôle admin du bot.
    """
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id == ctx.bot.owner_id:
            return True
        if await is_staff(ctx):
            return True
        raise commands.CheckFailure(
            "Réservé au staff : administrateur Discord ou rôle admin du bot (`+setadminrole`)."
        )

    return commands.check(predicate)


async def interaction_is_staff(interaction: discord.Interaction) -> bool:
    """
    Même logique que is_staff pour les boutons / modals (pas de Context).
    """
    client = interaction.client
    if interaction.user.id == getattr(client, "owner_id", None):
        return True
    guild = interaction.guild
    if not guild:
        return False
    member = interaction.user
    if not isinstance(member, discord.Member):
        try:
            member = await guild.fetch_member(interaction.user.id)
        except Exception:
            return False
    if member.guild_permissions.administrator:
        return True
    config = (await get_guild_config(guild.id)) or {}
    admin_role_id = config.get("admin_role_id")
    try:
        admin_role_id = int(admin_role_id) if admin_role_id is not None else None
    except (TypeError, ValueError):
        admin_role_id = None
    if admin_role_id and any(r.id == admin_role_id for r in member.roles):
        return True
    return False
