"""
Utilitaires pour les embeds stylisés
"""
import discord
from typing import Optional
from config import DEFAULT_COLOR


def get_progress_bar(current: int, maximum: int, length: int = 20) -> str:
    """Génère une barre de progression visuelle"""
    if maximum <= 0:
        maximum = 1
    progress = min(1.0, current / maximum)
    filled = int(progress * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"`{bar}` {progress*100:.0f}%"


def success_embed(title: str, description: str, color: int = DEFAULT_COLOR) -> discord.Embed:
    """Embed de succès"""
    embed = discord.Embed(
        title=f"✅ {title}",
        description=description,
        color=color,
    )
    embed.set_footer(text="Opération réussie")
    return embed


def error_embed(title: str, description: str) -> discord.Embed:
    """Embed d'erreur (rouge)"""
    embed = discord.Embed(
        title=f"❌ {title}",
        description=description,
        color=0xED4245,
    )
    embed.set_footer(text="Une erreur s'est produite")
    return embed


def info_embed(title: str, description: str, color: int = DEFAULT_COLOR) -> discord.Embed:
    """Embed d'information"""
    embed = discord.Embed(
        title=f"ℹ️ {title}",
        description=description,
        color=color,
    )
    return embed


def separator() -> str:
    """Séparateur visuel"""
    return "━━━━━━━━━━━━━━━━━━━━"
