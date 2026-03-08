"""
Configuration centrale du bot
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Discord
TOKEN = os.getenv("TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# MongoDB
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# Valeurs par défaut
DEFAULT_PREFIX = "+"
DEFAULT_COLOR = 0x5865F2  # Bleu Discord
DEFAULT_CURRENCY_NAME = "SayuCoins"
DEFAULT_CURRENCY_EMOJI = "💰"
DEFAULT_XP_NAME = "XP"
DEFAULT_LEVEL_UP_MSG = "🎉 Félicitations {user} ! Tu passes au niveau **{level}** !"
DEFAULT_SHOP_NAME = "Sayuri Shop"
