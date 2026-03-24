"""
Rôles automatiques selon nombre de messages ou minutes vocales (config par serveur).
Annonces dans rank_announce_channel_id (optionnel).
"""
from typing import Any, List

import discord

from database import get_collection
from utils.embeds import success_embed
from utils.guild_config import get_guild_config, get_guild_color


async def get_total_messages(guild_id: int, user_id: int) -> int:
    col = get_collection("message_stats")
    if col is None:
        return 0
    pipeline = [
        {"$match": {"guild_id": str(guild_id), "user_id": str(user_id)}},
        {"$group": {"_id": None, "total": {"$sum": "$count"}}},
    ]
    async for doc in col.aggregate(pipeline):
        return int(doc.get("total", 0))
    return 0


async def get_total_voice_minutes(guild_id: int, user_id: int) -> int:
    col = get_collection("voice_stats")
    if col is None:
        return 0
    pipeline = [
        {"$match": {"guild_id": str(guild_id), "user_id": str(user_id)}},
        {"$group": {"_id": None, "total": {"$sum": "$minutes"}}},
    ]
    async for doc in col.aggregate(pipeline):
        return int(doc.get("total", 0))
    return 0


def normalize_message_milestones(raw: Any) -> List[dict]:
    """Liste triée par nombre de messages croissant."""
    return _norm_message_milestones(raw)


def _norm_message_milestones(raw: Any) -> List[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        rid = item.get("role_id")
        msg = item.get("messages")
        if rid is None or msg is None:
            continue
        try:
            out.append({"role_id": int(rid), "messages": max(1, int(msg))})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x["messages"])
    return out


def normalize_voice_milestones(raw: Any) -> List[dict]:
    """Liste triée par minutes croissantes (usage affichage + logique)."""
    return _norm_voice_milestones(raw)


def _norm_voice_milestones(raw: Any) -> List[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        rid = item.get("role_id")
        mins = item.get("minutes")
        if rid is None or mins is None:
            continue
        try:
            out.append({"role_id": int(rid), "minutes": max(1, int(mins))})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x["minutes"])
    return out


async def _announce(
    guild: discord.Guild,
    member: discord.Member,
    title: str,
    description: str,
) -> None:
    conf = await get_guild_config(guild.id)
    cid = conf.get("rank_announce_channel_id")
    if not cid:
        return
    ch = guild.get_channel(int(cid))
    if not ch or not isinstance(ch, discord.TextChannel):
        return
    color = await get_guild_color(guild.id)
    try:
        await ch.send(embed=success_embed(title, description, color))
    except Exception:
        pass


async def apply_message_milestones(_bot, member: discord.Member) -> None:
    if member.bot or not member.guild:
        return
    guild = member.guild
    conf = await get_guild_config(guild.id)
    milestones = normalize_message_milestones(conf.get("message_role_milestones"))
    if not milestones:
        return
    total = await get_total_messages(guild.id, member.id)
    added: List[str] = []
    for m in milestones:
        if total < m["messages"]:
            continue
        role = guild.get_role(m["role_id"])
        if not role or role in member.roles:
            continue
        try:
            await member.add_roles(role, reason="Palier messages atteint")
            added.append(role.name)
        except Exception:
            continue
    if added:
        await _announce(
            guild,
            member,
            "💬 Rôle message obtenu !",
            f"{member.mention} a débloqué : **{', '.join(added)}** "
            f"({total:,} messages au total).",
        )


async def apply_voice_milestones(_bot, member: discord.Member) -> None:
    if member.bot or not member.guild:
        return
    guild = member.guild
    conf = await get_guild_config(guild.id)
    milestones = normalize_voice_milestones(conf.get("voice_role_milestones"))
    if not milestones:
        return
    total = await get_total_voice_minutes(guild.id, member.id)
    added: List[str] = []
    for m in milestones:
        if total < m["minutes"]:
            continue
        role = guild.get_role(m["role_id"])
        if not role or role in member.roles:
            continue
        try:
            await member.add_roles(role, reason="Palier vocal atteint")
            added.append(role.name)
        except Exception:
            continue
    if added:
        h = total // 60
        rest = total % 60
        time_txt = f"{h}h{rest:02d}min" if h else f"{total} min"
        await _announce(
            guild,
            member,
            "🎤 Rôle vocal obtenu !",
            f"{member.mention} a débloqué : **{', '.join(added)}** "
            f"({time_txt} en vocal au total).",
        )
