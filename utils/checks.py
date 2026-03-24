"""
Vérifications de permissions
"""
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
    "shop", "inventory", "glist",
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
