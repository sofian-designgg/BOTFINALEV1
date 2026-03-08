"""
Module de connexion MongoDB avec Motor (async)
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL

_client = None
_db = None


async def connect_db():
    """Connexion à MongoDB"""
    global _client, _db
    try:
        _client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        await _client.admin.command('ping')
        _db = _client["discord_bot"]
        return True
    except Exception:
        return False


async def close_db():
    """Fermer la connexion"""
    global _client
    if _client:
        _client.close()


def get_db():
    """Obtenir la base de données"""
    return _db


def get_collection(name: str):
    """Obtenir une collection"""
    if _db is None:
        return None
    return _db[name]


async def is_connected():
    """Vérifier si MongoDB est connecté"""
    if _client is None:
        return False
    try:
        await _client.admin.command('ping')
        return True
    except Exception:
        return False
