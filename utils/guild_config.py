"""
Gestion des configurations par serveur (MongoDB)
"""
from database import get_collection
from config import (
    DEFAULT_PREFIX, DEFAULT_COLOR, DEFAULT_CURRENCY_NAME,
    DEFAULT_CURRENCY_EMOJI, DEFAULT_XP_NAME, DEFAULT_LEVEL_UP_MSG,
    DEFAULT_SHOP_NAME
)


DEFAULT_GUILD_CONFIG = {
    "prefix": DEFAULT_PREFIX,
    "color": DEFAULT_COLOR,
    "currency_name": DEFAULT_CURRENCY_NAME,
    "currency_emoji": DEFAULT_CURRENCY_EMOJI,
    "xp_name": DEFAULT_XP_NAME,
    "level_up_msg": DEFAULT_LEVEL_UP_MSG,
    "shop_name": DEFAULT_SHOP_NAME,
    "log_channel_id": None,
    "welcome_channel_id": None,
    "welcome_msg": "Bienvenue {user} sur **{server}** ! 👋",
    "leave_msg": "{user} a quitté le serveur. 👋",
    "mute_role_id": None,
    "admin_role_id": None,
}


async def get_guild_config(guild_id: int) -> dict:
    """Récupère la config d'un serveur"""
    col = get_collection("guild_configs")
    if col is None:
        return DEFAULT_GUILD_CONFIG.copy()
    try:
        doc = await col.find_one({"_id": str(guild_id)})
        if doc:
            config = DEFAULT_GUILD_CONFIG.copy()
            for k, v in doc.items():
                if k != "_id":
                    config[k] = v
            return config
    except Exception:
        pass
    return DEFAULT_GUILD_CONFIG.copy()


async def update_guild_config(guild_id: int, updates: dict):
    """Met à jour la config d'un serveur"""
    col = get_collection("guild_configs")
    if col is None:
        return
    try:
        await col.update_one(
            {"_id": str(guild_id)},
            {"$set": updates},
            upsert=True
        )
    except Exception:
        pass


async def get_prefix(bot, message) -> str:
    """Callback pour récupérer le préfixe (dynamique)"""
    if not message.guild:
        return DEFAULT_PREFIX
    config = await get_guild_config(message.guild.id)
    return config.get("prefix", DEFAULT_PREFIX)


async def get_guild_color(guild_id: int) -> int:
    """Couleur du serveur pour les embeds"""
    config = await get_guild_config(guild_id)
    color = config.get("color", DEFAULT_COLOR)
    if isinstance(color, str):
        color = color.lstrip("#")
        if len(color) == 6:
            return int(color, 16)
    return int(color) if color else DEFAULT_COLOR
