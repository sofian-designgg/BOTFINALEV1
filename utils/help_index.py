"""
Index global des commandes (ordre stable) pour +help numéroté et +detail <n>.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from discord.ext import commands

# Emoji affiché devant le nom du module dans +help
COG_EMOJI = {
    "ConfigCog": "⚙️",
    "HelpCog": "📚",
    "DetailCog": "📖",
    "DatabaseCog": "🗄️",
    "ModerationCog": "🛡️",
    "XPCog": "📊",
    "MinigamesCog": "🎮",
    "StatsCog": "📈",
    "EconomyCog": "💰",
    "ShopCog": "🛒",
    "LicenseCog": "🔑",
    "AnnouncementsCog": "📢",
    "GiveawayCog": "🎉",
    "FameCog": "⭐",
    "StreaksCog": "🔥",
    "InvitesCog": "📨",
    "VoiceRolesCog": "🎤",
    "CasinoCog": "🎰",
    "WelcomeCog": "👋",
}


def cog_field_title(cog_name: Optional[str]) -> str:
    cn = cog_name or "BOT"
    emoji = COG_EMOJI.get(cog_name or "", "📦")
    short = cn.replace("Cog", "").replace("_", " ").strip() or "GÉNÉRAL"
    return f"{emoji} {short.upper()}"


def flatten_commands(bot: commands.Bot) -> List[commands.Command]:
    """Toutes les commandes (y compris hidden), ordre stable : module puis nom."""
    cmds = list(bot.walk_commands())
    cmds.sort(key=lambda c: ((c.cog_name or "ZZZ"), c.qualified_name.lower()))
    return cmds


def command_by_index(bot: commands.Bot, index_1based: int) -> Optional[commands.Command]:
    cmds = flatten_commands(bot)
    if 1 <= index_1based <= len(cmds):
        return cmds[index_1based - 1]
    return None


def index_for_command(bot: commands.Bot, cmd: commands.Command) -> Optional[int]:
    cmds = flatten_commands(bot)
    try:
        return cmds.index(cmd) + 1
    except ValueError:
        return None


def build_numbered_sections(bot: commands.Bot) -> List[Tuple[str, List[str]]]:
    """
    Retourne [(titre_champ, [lignes]), ...] une section par cog, lignes numérotées globalement.
    """
    flat = flatten_commands(bot)
    sections: List[Tuple[str, List[str]]] = []
    current_cog: Optional[str] = None
    lines: List[str] = []
    for i, cmd in enumerate(flat, start=1):
        cog = cmd.cog_name
        if cog != current_cog:
            if lines:
                sections.append((cog_field_title(current_cog), lines))
            current_cog = cog
            lines = []
        lines.append(f"{i}.`{cmd.qualified_name.upper()}`")
    if lines:
        sections.append((cog_field_title(current_cog), lines))
    return sections


def chunk_lines(lines: List[str], max_len: int = 1000) -> List[str]:
    """Découpe une liste de lignes en blocs ≤ max_len (séparateur \\n uniquement, pas de lignes vides)."""
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for line in lines:
        sep = 1 if cur else 0
        if cur and cur_len + sep + len(line) > max_len:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur_len += sep + len(line)
            cur.append(line)
    if cur:
        chunks.append("\n".join(cur))
    return chunks
