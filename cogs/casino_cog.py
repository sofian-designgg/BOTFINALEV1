"""
Casino : mises SayuCoins, leaderboard, config (boutons), enchères de rôles, trade
"""
import random
import asyncio
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import discord
from discord import InteractionType, SelectOption
from discord.ext import commands
from discord.ui import Button, View, Select, Modal, TextInput

from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color
from cogs.economy_cog import get_balance, add_coins, remove_coins

DEFAULT_CASINO = {
    "min_bet": 10,
    "max_bet": 50000,
    "cooldown_seconds": 15,
    "daily_game_limit": 80,
    "house_fee_percent": 5,
    "auction_channel_id": None,
    "casino_channel_id": None,
    "channel_slots": None,
    "channel_flip": None,
    "channel_pfc": None,
    "channel_blackjack": None,
    "channel_leaderboard": None,
    "channel_trade": None,
    "enabled": True,
    "games": {"slots": True, "flip": True, "blackjack": True, "pfc": True},
    "auction_fee_percent": 0,
    "bid_increment_min": 100,
    "last_games_channel_id": None,
    "last_games_message_id": None,
}


def _channel_for_game(cfg: dict, game: str) -> Optional[int]:
    """Salon pour un jeu : spécifique → sinon salon casino global → sinon partout (None)."""
    key = {"slots": "channel_slots", "flip": "channel_flip", "pfc": "channel_pfc", "blackjack": "channel_blackjack"}.get(game)
    if not key:
        return cfg.get("casino_channel_id")
    cid = cfg.get(key)
    if cid:
        return cid
    return cfg.get("casino_channel_id")


async def _must_be_channel(ctx, cfg: dict, channel_key: str) -> Optional[str]:
    """Si channel_key est défini, la commande doit être utilisée dans ce salon."""
    cid = cfg.get(channel_key)
    if not cid:
        return None
    if ctx.channel.id != cid:
        ch = ctx.guild.get_channel(cid)
        return f"Utilisez ce salon : {ch.mention}." if ch else "Salon casino non configuré."
    return None


async def get_casino_config(gid: int) -> dict:
    col = get_collection("casino_config")
    if col is None:
        return {**DEFAULT_CASINO}
    doc = await col.find_one({"_id": str(gid)})
    if not doc:
        return {**DEFAULT_CASINO}
    cfg = {**DEFAULT_CASINO}
    for k, v in doc.items():
        if k != "_id":
            cfg[k] = v
    return cfg


async def update_casino_config(gid: int, data: dict):
    col = get_collection("casino_config")
    if col is None:
        return
    await col.update_one({"_id": str(gid)}, {"$set": data}, upsert=True)


async def _update_last_games_message(guild: discord.Guild, entry: str):
    """Met à jour le message 'Dernières parties' (si configuré)."""
    cfg = await get_casino_config(guild.id)
    cid = cfg.get("last_games_channel_id")
    if not cid:
        return
    ch = guild.get_channel(int(cid))
    if not isinstance(ch, discord.TextChannel):
        return
    mid = cfg.get("last_games_message_id")
    color = await get_guild_color(guild.id)
    title = "🕘 Dernières parties — Casino"
    # On stocke l'historique en mémoire DB (casino_config) pour éviter de fetch+parser le message
    col = get_collection("casino_last_games")
    if col is None:
        return
    await col.update_one(
        {"_id": str(guild.id)},
        {"$push": {"lines": {"$each": [entry], "$slice": -15}}},
        upsert=True,
    )
    doc = await col.find_one({"_id": str(guild.id)}) or {}
    lines = doc.get("lines", [])
    desc = "\n".join(lines) if lines else "Aucune partie pour le moment."
    emb = discord.Embed(title=title, description=desc, color=color)
    emb.set_footer(text="Auto update • configure: +casinoset lastgames #salon")
    msg = None
    if mid:
        try:
            msg = await ch.fetch_message(int(mid))
        except Exception:
            msg = None
    if msg:
        try:
            await msg.edit(embed=emb, view=None)
        except Exception:
            pass
    else:
        try:
            m = await ch.send(embed=emb)
            await update_casino_config(guild.id, {"last_games_message_id": str(m.id)})
        except Exception:
            pass


async def inc_casino_stat(gid: int, uid: int, wagered: int = 0, won: int = 0):
    col = get_collection("casino_stats")
    if col is None:
        return
    net = won - wagered
    await col.update_one(
        {"guild_id": str(gid), "user_id": str(uid)},
        {"$inc": {"wagered": wagered, "won": won, "net": net, "games": 1}},
        upsert=True,
    )


_cooldown_mem: dict[str, float] = {}


def _cd_key(gid: int, uid: int, game: str) -> str:
    return f"{gid}:{uid}:{game}"


DEFAULT_CASINO_RANKS = [
    {"emoji": "🎲", "name": "Casino - Débutant", "color": 0x95A5A6, "req_net": 0, "req_games": 0,
     "desc": "Tu apprends : no stress, casino classique.",
     "bonus": {"cooldown_minus": 0, "win_bonus_pct": 0, "slots_luck": 0.00, "flip_luck": 0.00, "pfc_luck": 0.00}},
    {"emoji": "🪙", "name": "Casino - Joueur", "color": 0x2ECC71, "req_net": 2_000, "req_games": 20,
     "desc": "Un premier boost pour enchaîner sans trop attendre.",
     "bonus": {"cooldown_minus": 1, "win_bonus_pct": 1, "slots_luck": 0.01, "flip_luck": 0.00, "pfc_luck": 0.00}},
    {"emoji": "🍀", "name": "Casino - Chanceux", "color": 0x1ABC9C, "req_net": 6_000, "req_games": 60,
     "desc": "Un peu plus de chance sur tes décisions (flip & PFC).",
     "bonus": {"cooldown_minus": 2, "win_bonus_pct": 1, "slots_luck": 0.02, "flip_luck": 0.01, "pfc_luck": 0.01}},
    {"emoji": "🎰", "name": "Casino - Addict Slots", "color": 0x9B59B6, "req_net": 12_000, "req_games": 120,
     "desc": "Spécialiste des slots : 💎 et 7️⃣ reviennent un peu plus souvent.",
     "bonus": {"cooldown_minus": 3, "win_bonus_pct": 2, "slots_luck": 0.04, "flip_luck": 0.00, "pfc_luck": 0.00}},
    {"emoji": "🃏", "name": "Casino - Stratège", "color": 0x5865F2, "req_net": 25_000, "req_games": 200,
     "desc": "Tu joues propre : gains nets un peu plus élevés, approche plus stable.",
     "bonus": {"cooldown_minus": 4, "win_bonus_pct": 2, "slots_luck": 0.00, "flip_luck": 0.00, "pfc_luck": 0.00}},
    {"emoji": "🔥", "name": "Casino - High Roller", "color": 0xE67E22, "req_net": 45_000, "req_games": 300,
     "desc": "Le chaud : cooldown réduit et bonus sur le net.",
     "bonus": {"cooldown_minus": 5, "win_bonus_pct": 3, "slots_luck": 0.01, "flip_luck": 0.00, "pfc_luck": 0.00}},
    {"emoji": "💎", "name": "Casino - VIP", "color": 0x00D1FF, "req_net": 80_000, "req_games": 450,
     "desc": "Le VIP a la main : un confort accru sur plusieurs jeux.",
     "bonus": {"cooldown_minus": 6, "win_bonus_pct": 3, "slots_luck": 0.02, "flip_luck": 0.01, "pfc_luck": 0.01}},
    {"emoji": "👑", "name": "Casino - Élite", "color": 0xF1C40F, "req_net": 130_000, "req_games": 650,
     "desc": "L’élite : gains nets améliorés et chance progressive.",
     "bonus": {"cooldown_minus": 7, "win_bonus_pct": 4, "slots_luck": 0.03, "flip_luck": 0.01, "pfc_luck": 0.01}},
    {"emoji": "🌟", "name": "Casino - Légende", "color": 0xFF4D4D, "req_net": 220_000, "req_games": 900,
     "desc": "Presque intouchable : boosts plus forts et cooldown très bas.",
     "bonus": {"cooldown_minus": 8, "win_bonus_pct": 4, "slots_luck": 0.04, "flip_luck": 0.02, "pfc_luck": 0.02}},
    {"emoji": "🧿", "name": "Casino - Mythique", "color": 0xB200FF, "req_net": 350_000, "req_games": 1_200,
     "desc": "Le mythique : maximum de confort + petites chances sur les jeux.",
     "bonus": {"cooldown_minus": 9, "win_bonus_pct": 5, "slots_luck": 0.05, "flip_luck": 0.02, "pfc_luck": 0.02}},
    {"emoji": "⚜️", "name": "Casino - Royal", "color": 0xFFD700, "req_net": 550_000, "req_games": 1_700,
     "desc": "Royal : tu joues au sommet, boosts solides partout.",
     "bonus": {"cooldown_minus": 10, "win_bonus_pct": 5, "slots_luck": 0.05, "flip_luck": 0.03, "pfc_luck": 0.03}},
    {"emoji": "🪽", "name": "Casino - Divin", "color": 0xFFFFFF, "req_net": 850_000, "req_games": 2_400,
     "desc": "Le divin : cooldown minimal et net amélioré (très léger).",
     "bonus": {"cooldown_minus": 11, "win_bonus_pct": 6, "slots_luck": 0.06, "flip_luck": 0.03, "pfc_luck": 0.03}},
]


async def get_casino_ranks_config(gid: int) -> dict:
    col = get_collection("casino_ranks_config")
    if col is None:
        return {"_id": str(gid), "enabled": False, "rank_channel_id": None, "panel_message_id": None, "ranks": []}
    doc = await col.find_one({"_id": str(gid)})
    if not doc:
        return {"_id": str(gid), "enabled": False, "rank_channel_id": None, "panel_message_id": None, "ranks": []}
    return doc


async def update_casino_ranks_config(gid: int, data: dict):
    col = get_collection("casino_ranks_config")
    if col is None:
        return
    await col.update_one({"_id": str(gid)}, {"$set": data}, upsert=True)


async def get_member_casino_rank_bonus(guild: discord.Guild, member: discord.Member) -> dict:
    cfg = await get_casino_ranks_config(guild.id)
    ranks = cfg.get("ranks") or []
    if not cfg.get("enabled") or not ranks:
        return {"cooldown_minus": 0, "win_bonus_pct": 0, "slots_luck": 0.0, "flip_luck": 0.0, "pfc_luck": 0.0}
    owned = {r.id for r in member.roles}
    best = None
    for r in ranks:
        rid = r.get("role_id")
        if rid and int(rid) in owned:
            best = r
    if not best:
        return {"cooldown_minus": 0, "win_bonus_pct": 0, "slots_luck": 0.0, "flip_luck": 0.0, "pfc_luck": 0.0}
    b = (best.get("bonus") or {})
    return {
        "cooldown_minus": int(b.get("cooldown_minus", 0)),
        "win_bonus_pct": int(b.get("win_bonus_pct", 0)),
        "slots_luck": float(b.get("slots_luck", 0.0)),
        "flip_luck": float(b.get("flip_luck", 0.0)),
        "pfc_luck": float(b.get("pfc_luck", 0.0)),
    }


async def _casino_get_user_net_games(gid: int, uid: int) -> tuple[int, int]:
    col = get_collection("casino_stats")
    if col is None:
        return 0, 0
    doc = await col.find_one({"guild_id": str(gid), "user_id": str(uid)})
    net = int(doc.get("net", 0)) if doc else 0
    games = int(doc.get("games", 0)) if doc else 0
    return net, games


def _casino_best_rank_index(ranks: list, *, net: int, games: int) -> int:
    """Retourne l'index du meilleur rang validé (>=0)."""
    best = 0
    for i, r in enumerate(ranks):
        rn = int(r.get("req_net", 0))
        rg = int(r.get("req_games", 0))
        if net >= rn and games >= rg:
            best = i
    return best

async def check_casino_cooldown(gid: int, uid: int, game: str, seconds: int) -> tuple[bool, int]:
    k = _cd_key(gid, uid, game)
    now = time.time()
    last = _cooldown_mem.get(k, 0)
    if now - last < seconds:
        return False, int(seconds - (now - last))
    _cooldown_mem[k] = now
    return True, 0


async def get_daily_count(gid: int, uid: int) -> int:
    col = get_collection("casino_daily")
    if col is None:
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await col.find_one({"guild_id": str(gid), "user_id": str(uid), "date": today})
    return doc.get("count", 0) if doc else 0


async def inc_daily_count(gid: int, uid: int):
    col = get_collection("casino_daily")
    if col is None:
        return
    today = datetime.now(timezone.utc).date().isoformat()
    await col.update_one(
        {"guild_id": str(gid), "user_id": str(uid), "date": today},
        {"$inc": {"count": 1}},
        upsert=True,
    )


async def validate_bet(ctx, bet: int, game: str) -> Optional[str]:
    cfg = await get_casino_config(ctx.guild.id)
    if not cfg.get("enabled", True):
        return "Le casino est désactivé sur ce serveur."
    need = _channel_for_game(cfg, game)
    if need and ctx.channel.id != need:
        ch = ctx.guild.get_channel(need)
        return f"Jouez à **{game}** dans {ch.mention}." if ch else "Salon jeu non configuré."
    if not cfg.get("games", {}).get(game, True):
        return "Ce jeu est désactivé."
    if bet < cfg["min_bet"]:
        return f"Mise minimale : **{cfg['min_bet']}**"
    if bet > cfg["max_bet"]:
        return f"Mise maximale : **{cfg['max_bet']}**"
    bal = await get_balance(ctx.guild.id, ctx.author.id)
    if bal < bet:
        return f"Pas assez de SayuCoins pour cette mise : il te faut **{bet}**, tu as **{bal}**. (Gagne des coins avec +daily, +weekly, messages, etc.)"
    bonus = await get_member_casino_rank_bonus(ctx.guild, ctx.author)
    eff_cd = max(1, int(cfg["cooldown_seconds"]) - int(bonus.get("cooldown_minus", 0)))
    ok_cd, left = await check_casino_cooldown(ctx.guild.id, ctx.author.id, game, eff_cd)
    if not ok_cd:
        return f"Cooldown : attendez **{left}s**."
    used = await get_daily_count(ctx.guild.id, ctx.author.id)
    if used >= cfg["daily_game_limit"]:
        return f"Limite journalière atteinte (**{cfg['daily_game_limit']}** parties)."
    return None


async def after_bet_ok(ctx, game: str):
    await inc_daily_count(ctx.guild.id, ctx.author.id)


async def take_house_fee(gross_win: int, fee_pct: int) -> int:
    if gross_win <= 0:
        return 0
    fee = int(gross_win * fee_pct / 100)
    return max(0, gross_win - fee)


def apply_rank_win_bonus(net: int, bonus_pct: int) -> int:
    if net <= 0:
        return 0
    bonus_pct = int(bonus_pct or 0)
    if bonus_pct <= 0:
        return net
    return int(net * (1 + bonus_pct / 100))


def _casino_help_full_embeds(color: int) -> List[discord.Embed]:
    """Une entrée = une commande (ou alias), sans exception."""
    lines_joueurs = [
        ("`+helpcasino`", "Aide résumée. Alias : `+casinohelp`, `+aidecasino`."),
        ("`+helpcasinocomplet`", "Liste **exhaustive** de toutes les commandes casino (ce guide). Alias : `+casinolist`, `+listecasino`."),
        ("`+casinoconfig`", "Affiche la configuration casino (lecture seule, tout le monde)."),
        ("`+casinolb`", "Top 10 des gains **nets** au casino. Alias : `+casinoleaderboard`."),
        ("`+casinostats`", "Tes stats casino (misé, gagné, net, parties). `+casinostats @membre` pour un autre joueur."),
        ("`+casino`", "Sans argument : rappel des sous-commandes de jeu."),
        ("`+casino slots [mise]`", "Machine à sous. Tu paies la **mise** ; alignement = gain (taxe maison sur le gain)."),
        ("`+casino flip [mise] [pile|face]`", "Pile ou face. Si tu gagnes, gain brut x2 puis taxe ; si tu perds, tu perds la mise."),
        ("`+casino pfc [mise] [pierre|feuille|ciseaux]`", "Pierre-feuille-ciseaux vs le bot. Égalité = mise rendue ; victoire = gain avec taxe."),
        ("`+casino blackjack [mise]`", "Blackjack avec boutons Tirer / Rester. Bust = perte de la mise ; victoire = gain net après taxe."),
        ("`+sellrole @Rôle [prix_départ] [achat_immédiat]`", "Met un rôle aux enchères (tu dois le posséder). **Sans frais de dépôt** par défaut. Commande **dans le salon enchères**."),
        ("`+auctioncancel [id]`", "Annule **ta** vente. Les admins peuvent annuler n’importe quelle enchère. Salon enchères si configuré."),
        ("`+trade @Rôle *message*`", "Tu **proposes** un rôle que tu possèdes : annonce + **un seul** partenaire répond ; fil privé, choix du rôle en échange, double confirmation. `+tradecancel [id]` (auteur)."),
        ("`+casinoranks me`", "Ton rang casino, tes bonus, et ta progression vers le prochain grade."),
        ("`+hierarchie`", "Liste complète des ranks casino (index + descriptifs + bonus)."),
        ("`+embedslots` / `+embedflip` / `+embedpfc`", "Panels de jeu (embed + bouton) → mise → fil privé (postés par admin)."),
        ("`+balanceembed` / `+rankembed` / `+statsembed`", "Panels bouton (hors casino) : banque, rank XP, stats."),
        ("**Qui peut jouer ?**", "Tout membre du serveur (avec licence bot active) peut utiliser les jeux **sans être staff**. Seules les mises comptent : si ton solde < mise min ou < mise choisie, le bot refuse."),
    ]
    lines_admin = [
        ("`+casinopanel`", "Panneau admin avec boutons (rappels + ON/OFF casino). **Administrateur Discord** requis."),
        ("`+casinoset`", "Groupe parent : affiche la liste des sous-commandes si tu ne mets pas d’argument."),
        ("`+casinoset minbet [n]`", "Mise **minimum** (SayuCoins) pour jouer."),
        ("`+casinoset maxbet [n]`", "Mise **maximum**."),
        ("`+casinoset cooldown [secondes]`", "Temps d’attente entre deux parties **par jeu**."),
        ("`+casinoset daily [n]`", "Nombre max de parties casino **par jour et par membre**."),
        ("`+casinoset fee [0-50]`", "Pourcentage prélevé sur les **gains** (taxe maison)."),
        ("`+casinoset auctionfee [0-30]`", "Frais de dépôt sur +sellrole (**0** par défaut = aucun prélèvement)."),
        ("`+casinoset bidinc [n]`", "Montant minimum ajouté par clic d’enchère (hors boutons fixes +100/+500/+1000)."),
        ("`+casinoset auctionchannel #salon`", "Salon des **enchères** (+sellrole, +auctioncancel, messages d’enchère)."),
        ("`+casinoset casinochannel #salon`", "Salon **global** de secours si un jeu n’a pas son propre salon."),
        ("`+casinoset resetcasinochannel`", "Supprime le salon global (les jeux sans salon dédié = partout)."),
        ("`+casinoset resetchannels`", "Remet à zéro **tous** les salons jeu + leaderboard + trade (pas les enchères)."),
        ("`+casinoset setchannel …`", "Voir bloc suivant : **un salon par type**."),
        ("`+casinoset setchannel slots [#salon]`", "Salon **uniquement** pour +casino slots. Sans # = reset."),
        ("`+casinoset setchannel flip [#salon]`", "Salon pour +casino flip."),
        ("`+casinoset setchannel pfc [#salon]`", "Salon pour +casino pfc."),
        ("`+casinoset setchannel blackjack [#salon]`", "Salon pour +casino blackjack (alias accepté : `bj`)."),
        ("`+casinoset setchannel leaderboard [#salon]`", "Salon pour +casinolb et +casinostats. Alias : `lb`."),
        ("`+settradechannel [#salon]`", "Salon **uniquement** pour +trade (admin). Alias : `setchanneltrade`, `salontrade`. Sans salon = reset."),
        ("`+casinoset setchannel trade [#salon]`", "Identique à +settradechannel."),
        ("`+casinoset setchannel global [#salon]`", "Même effet que +casinoset casinochannel."),
        ("`+casinoset setchannel encheres [#salon]`", "Même effet que +casinoset auctionchannel."),
        ("`+casinoset chslots [#salon]` … `chbj`", "Raccourcis identiques à setchannel (slots, flip, pfc, chbj, chleaderboard, chtrade)."),
        ("`+casinoset game [slots|flip|pfc|blackjack] [on|off]`", "Active ou désactive un jeu."),
        ("`+setrankcasino #salon`", "Salon du panel ranks casino."),
        ("`+casinoranks setup`", "Crée les 12 rôles casino (emoji | nom) + hiérarchie."),
        ("`+casinoranks panel`", "Poste / met à jour le panel de progression (embed) dans le salon ranks."),
        ("`+casinoranks sync`", "Attribue le bon rang à tous (ou un membre) selon net + parties."),
        ("`+casinoranks setreq [index] [net] [parties]`", "Modifie les conditions d’un rang (0–11)."),
        ("`+casinoset lastgames [#salon]`", "Active le message auto « Dernières parties » dans un salon (sans salon = off)."),
        ("`+embedslots` `+embedflip` `+embedpfc` `+embedblackjack`", "Poste des panneaux de jeux (embed + bouton) : fil privé visible + bouton **Lancer la partie** + animations."),
    ]
    emb1 = discord.Embed(title="📜 Liste complète — Joueurs", color=color)
    emb1.description = "\n\n".join(f"**{cmd}**\n{desc}" for cmd, desc in lines_joueurs)
    emb2 = discord.Embed(title="📜 Liste complète — Admin (1/2)", color=color)
    half = len(lines_admin) // 2 + 1
    emb2.description = "\n\n".join(f"**{cmd}**\n{desc}" for cmd, desc in lines_admin[:half])
    emb3 = discord.Embed(title="📜 Liste complète — Admin (2/2)", color=color)
    emb3.description = "\n\n".join(f"**{cmd}**\n{desc}" for cmd, desc in lines_admin[half:])
    return [emb1, emb2, emb3]


class AuctionBidView(View):
    def __init__(self, auction_id: str):
        super().__init__(timeout=None)
        self.aid = auction_id
        self.add_item(Button(label="+100", style=discord.ButtonStyle.primary, custom_id=f"auc:{auction_id}:100"))
        self.add_item(Button(label="+500", style=discord.ButtonStyle.primary, custom_id=f"auc:{auction_id}:500"))
        self.add_item(Button(label="+1000", style=discord.ButtonStyle.success, custom_id=f"auc:{auction_id}:1000"))
        btn = Button(
            label="✅ Accepter l’offre (vendeur)",
            style=discord.ButtonStyle.danger,
            custom_id=f"auc:{auction_id}:accept",
            row=1,
        )

        async def cb(interaction: discord.Interaction):
            cog = interaction.client.get_cog("CasinoCog")
            if cog:
                await cog._handle_auc_accept(interaction, auction_id)
            elif not interaction.response.is_done():
                await interaction.response.send_message("Erreur interne.", ephemeral=True)

        btn.callback = cb
        self.add_item(btn)


class AuctionJoinView(View):
    """Bouton public : ajoute le membre au fil privé de l'enchère."""

    def __init__(self, auction_id: str):
        super().__init__(timeout=None)
        self.add_item(
            Button(
                label="Rejoindre l'enchère (fil privé)",
                style=discord.ButtonStyle.success,
                custom_id=f"aucjoin:{auction_id}",
            )
        )


async def _create_private_thread(channel: discord.abc.GuildChannel, name: str) -> discord.Thread:
    """Crée un fil privé sous un salon texte (non invitable)."""
    if not isinstance(channel, discord.TextChannel):
        raise TypeError("Le salon doit être un salon texte pour créer un fil privé.")
    return await channel.create_thread(
        name=name[:100],
        type=discord.ChannelType.private_thread,
        invitable=False,
        reason="Trade / enchère casino",
    )


async def _thread_add_user_safe(thread: discord.Thread, user: discord.abc.User) -> None:
    try:
        await thread.add_user(user)
    except discord.HTTPException:
        pass


def _tradable_roles(member: discord.Member, bot_me: discord.Member) -> List[discord.Role]:
    roles = []
    for r in member.roles:
        if r.is_default():
            continue
        if r.managed:
            continue
        if r >= bot_me.top_role:
            continue
        roles.append(r)
    roles.sort(key=lambda x: x.position, reverse=True)
    return roles[:25]


class CasinoGameBetModal(Modal):
    def __init__(self, game: str):
        super().__init__(title=f"Mise — {game}")
        self.game = game
        self.bet = TextInput(label="Combien tu mises ?", placeholder="Ex: 100", required=True, max_length=12)
        self.choice = TextInput(
            label="Choix (si nécessaire)",
            placeholder="flip: pile/face • pfc: pierre/feuille/ciseaux • slots/bj: laisse vide",
            required=False,
            max_length=20,
        )
        self.add_item(self.bet)
        self.add_item(self.choice)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("CasinoCog")
        if not cog:
            return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        await cog._handle_game_modal_submit(interaction, self.game, str(self.bet.value), str(self.choice.value or ""))


class CasinoGameEntryView(View):
    def __init__(self, game: str):
        super().__init__(timeout=None)
        self.game = game
        btn = Button(
            label="🎮 Lancer une partie",
            style=discord.ButtonStyle.success,
            custom_id=f"cg:start:{game}",
        )

        async def cb(interaction: discord.Interaction):
            if not interaction.guild:
                return
            try:
                await interaction.response.send_modal(CasinoGameBetModal(game))
            except discord.HTTPException:
                await interaction.response.send_message("Impossible d’ouvrir le formulaire.", ephemeral=True)

        btn.callback = cb
        self.add_item(btn)


class CasinoGameStartView(View):
    def __init__(self, game_id: str):
        super().__init__(timeout=None)
        btn = Button(
            label="▶️ Lancer la partie",
            style=discord.ButtonStyle.success,
            custom_id=f"cgplay:{game_id}",
        )

        async def cb(interaction: discord.Interaction):
            cog = interaction.client.get_cog("CasinoCog")
            if cog:
                await cog._handle_cgplay(interaction, game_id)
            elif not interaction.response.is_done():
                await interaction.response.send_message("Erreur interne.", ephemeral=True)

        btn.callback = cb
        self.add_item(btn)


class TradeOpenView(View):
    """Un seul membre peut répondre (premier cliqué)."""

    def __init__(self, trade_id: str):
        super().__init__(timeout=None)
        tid = trade_id
        btn = Button(
            label="Je réponds au trade (1 place)",
            style=discord.ButtonStyle.success,
            custom_id=f"rtclaim:{tid}",
        )

        async def cb(interaction: discord.Interaction):
            cog = interaction.client.get_cog("CasinoCog")
            if cog:
                await cog._handle_rtclaim(interaction, tid)
            elif not interaction.response.is_done():
                await interaction.response.send_message("Erreur interne.", ephemeral=True)

        btn.callback = cb
        self.add_item(btn)


class TradeFinalView(View):
    """Double validation avant échange de rôles."""

    def __init__(self, trade_id: str):
        super().__init__(timeout=None)
        tid = trade_id
        for label, side in [
            ("✅ Confirmer (auteur du trade)", "author"),
            ("✅ Confirmer (partenaire)", "claimer"),
        ]:
            b = Button(
                label=label,
                style=discord.ButtonStyle.success,
                custom_id=f"rtconf:{tid}:{side}",
                row=0,
            )

            async def cb(interaction: discord.Interaction, *, s=side):
                cog = interaction.client.get_cog("CasinoCog")
                if cog:
                    await cog._handle_rtconf(interaction, tid, s)
                elif not interaction.response.is_done():
                    await interaction.response.send_message("Erreur interne.", ephemeral=True)

            b.callback = cb
            self.add_item(b)


def build_trade_negotiation_view(trade_id: str, select_options: list) -> View:
    """Menu partenaire + bouton auteur (fil privé)."""
    v = View(timeout=None)
    tid = trade_id
    sel = Select(
        custom_id=f"rtsela:{tid}",
        placeholder="Partenaire : choisis le rôle que tu donnes",
        options=select_options[:25],
        row=0,
    )

    async def scb(interaction: discord.Interaction):
        cog = interaction.client.get_cog("CasinoCog")
        if cog:
            await cog._handle_rtsela(interaction, tid)
        elif not interaction.response.is_done():
            await interaction.response.send_message("Erreur interne.", ephemeral=True)

    sel.callback = scb
    v.add_item(sel)
    btn = Button(
        label="Auteur : je confirme céder le rôle proposé",
        style=discord.ButtonStyle.primary,
        custom_id=f"rtgivew:{tid}",
        row=1,
    )

    async def bcb(interaction: discord.Interaction):
        cog = interaction.client.get_cog("CasinoCog")
        if cog:
            await cog._handle_rtgivew(interaction, tid)
        elif not interaction.response.is_done():
            await interaction.response.send_message("Erreur interne.", ephemeral=True)

    btn.callback = bcb
    v.add_item(btn)
    return v


class CasinoConfigView(View):
    """Boutons admin — renvoie vers les commandes +casinoset (fiable)"""

    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📖 Aide commandes", style=discord.ButtonStyle.primary, row=0)
    async def b1(self, interaction: discord.Interaction, btn: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Admin requis.", ephemeral=True)
            return
        txt = (
            "**Réglages rapides (tapez dans le salon) :**\n"
            "`+casinoset minbet 50` · `+casinoset maxbet 50000`\n"
            "`+casinoset cooldown 15` · `+casinoset daily 80`\n"
            "`+casinoset fee 5` · `+casinoset auctionfee 0` (dépôt enchère, 0 = off)\n"
            "`+casinoset bidinc 100`\n"
            "`+casinoset auctionchannel #salon` · `chslots` `chflip` `chpfc` `chbj` `chleaderboard` `chtrade`\n"
            "`+casinoset casinochannel` · `resetcasinochannel` · `resetchannels`\n"
            "`+casinoset game slots on` · `flip off` …\n"
            "`+casinoconfig` — lire la config"
        )
        await interaction.response.send_message(txt, ephemeral=True)

    @discord.ui.button(label="ON / OFF casino", style=discord.ButtonStyle.danger, row=0)
    async def b2(self, interaction: discord.Interaction, btn: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Admin requis.", ephemeral=True)
            return
        cfg = await get_casino_config(interaction.guild.id)
        new = not cfg.get("enabled", True)
        await update_casino_config(interaction.guild.id, {"enabled": new})
        await interaction.response.send_message(f"Casino : **{'ACTIVÉ' if new else 'DÉSACTIVÉ'}**", ephemeral=True)

    @discord.ui.button(label="Salons (IDs)", style=discord.ButtonStyle.secondary, row=1)
    async def b3(self, interaction: discord.Interaction, btn: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Admin requis.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Collez l’ID du salon (clic droit → Copier l’identifiant) puis :\n"
            "`+casinoset auctionchannel #encheres`\n"
            "`+casinoset casinochannel #casino` · `+casinoset resetcasinochannel` (jeu partout)",
            ephemeral=True,
        )

    @discord.ui.button(label="Taxe & limites", style=discord.ButtonStyle.secondary, row=1)
    async def b4(self, interaction: discord.Interaction, btn: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Admin requis.", ephemeral=True)
            return
        await interaction.response.send_message(
            "`+casinoset fee 5` — taxe sur les gains (0–50%)\n"
            "`+casinoset daily 80` — max parties casino / jour / membre\n"
            "`+casinoset cooldown 15` — secondes entre 2 jeux",
            ephemeral=True,
        )


class CasinoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="helpcasino", aliases=["casinohelp", "aidecasino"])
    async def helpcasino(self, ctx):
        color = await get_guild_color(ctx.guild.id)
        embed = discord.Embed(title="🎰 AIDE CASINO — COMMANDES DÉTAILLÉES", color=color)
        embed.add_field(
            name="🎮 Jeux (mise en SayuCoins)",
            value="`+casino slots [mise]` — Machine à sous (alignement = gain)\n"
            "`+casino flip [mise] [pile|face]` — Double ou rien (taxe sur gain)\n"
            "`+casino pfc [mise] [pierre|feuille|ciseaux]` — Pierre-feuille-ciseaux\n"
            "`+casino blackjack [mise]` — Tirer / Rester vs croupier\n"
            "Chaque jeu consomme une « partie » du quota journalier et respecte le cooldown.",
            inline=False,
        )
        embed.add_field(
            name="📊 Stats",
            value="`+casinolb` — Top 10 net\n`+casinostats` — Détail perso\n"
            "(Si `chleaderboard` est défini, ces commandes ne sont utilisables que dans ce salon.)",
            inline=False,
        )
        embed.add_field(
            name="⚙️ Salons distincts (admin)",
            value="**4 jeux** : `+casinoset setchannel slots|flip|pfc|blackjack #` (ou `chslots` … `chbj`)\n"
            "**Leaderboard** : `setchannel leaderboard` (`chleaderboard`) · **Trade** : `+settradechannel #` ou `chtrade`\n"
            "**Enchères** : `setchannel encheres #` ou `auctionchannel` · **Fallback global** : `setchannel global` ou `casinochannel`\n"
            "`+casinoset resetchannels` — reset jeux+lb+trade (pas les enchères)",
            inline=False,
        )
        embed.add_field(
            name="⚙️ Config (admin)",
            value="`+casinopanel` · `+casinoconfig` · `+casinoset` minbet, maxbet, cooldown, daily, fee, auctionchannel, game …",
            inline=False,
        )
        embed.add_field(
            name="🏆 Ranks Casino (progression)",
            value="`+casinoranks me` — ton rang + progression\n"
            "`+casinoranks panel` — (admin) poste/maj le panel dans le salon ranks\n"
            "`+casinoranks setup` — (admin) crée la hiérarchie de rôles\n"
            "`+setrankcasino #salon` — (admin) définit le salon panel",
            inline=False,
        )
        embed.add_field(
            name="🏷️ Hiérarchie Casino",
            value="`+hierarchie` — la liste complète (index + descriptifs).",
            inline=False,
        )
        embed.add_field(
            name="✨ Panels de jeux (embed + bouton)",
            value="`+embedslots` `+embedflip` `+embedpfc` `+embedblackjack` — poste un panneau qui lance une partie en **fil privé**.\n"
            "`+casinoset lastgames #salon` — message auto « Dernières parties ».",
            inline=False,
        )
        embed.add_field(
            name="🏷️ Enchères de rôles",
            value="`+sellrole` et `+auctioncancel` dans le salon **enchères** (`+casinoset auctionchannel`). "
            "Boutons +100 / +500 / +1000 / achat immédiat.",
            inline=False,
        )
        embed.add_field(
            name="🤝 Trade",
            value="`+trade` — si un salon trade est défini (`+settradechannel` / `chtrade`), uniquement dans ce salon.",
            inline=False,
        )
        embed.add_field(
            name="🏦 Panels utiles (hors casino)",
            value="`+balanceembed` — bouton solde (banque)\n"
            "`+rankembed` — bouton rank XP\n"
            "`+statsembed` — bouton stats (messages/vocal)",
            inline=False,
        )
        embed.set_footer(text="Liste exhaustive sans exception : +helpcasinocomplet · Tout le monde peut jouer si solde ≥ mise min.")
        await ctx.send(embed=embed)

    @commands.command(name="helpcasinocomplet", aliases=["casinolist", "listecasino"])
    async def helpcasinocomplet(self, ctx):
        color = await get_guild_color(ctx.guild.id)
        for emb in _casino_help_full_embeds(color):
            await ctx.send(embed=emb)

    @commands.command(name="casinoconfig")
    async def casinoconfig(self, ctx):
        cfg = await get_casino_config(ctx.guild.id)
        color = await get_guild_color(ctx.guild.id)
        def mch(k):
            c = ctx.guild.get_channel(cfg.get(k)) if cfg.get(k) else None
            return c.mention if c else "— (partout)"

        ch_c = ctx.guild.get_channel(cfg["casino_channel_id"]) if cfg.get("casino_channel_id") else None
        ch_a = ctx.guild.get_channel(cfg["auction_channel_id"]) if cfg.get("auction_channel_id") else None
        games = cfg.get("games", {})
        gtxt = " · ".join(f"{k}={'✅' if v else '❌'}" for k, v in games.items())
        embed = discord.Embed(title="⚙️ Configuration casino", color=color)
        embed.add_field(name="Actif", value="✅" if cfg.get("enabled") else "❌", inline=True)
        embed.add_field(name="Mise min / max", value=f"{cfg['min_bet']} / {cfg['max_bet']}", inline=True)
        embed.add_field(name="Cooldown", value=f"{cfg['cooldown_seconds']} s", inline=True)
        embed.add_field(name="Parties / jour / membre", value=str(cfg["daily_game_limit"]), inline=True)
        embed.add_field(name="Taxe gains", value=f"{cfg['house_fee_percent']} %", inline=True)
        embed.add_field(name="Frais dépôt enchère (+sellrole)", value=f"{cfg.get('auction_fee_percent', 0)} % (0 = gratuit)", inline=True)
        embed.add_field(
            name="🎮 Salons par jeu",
            value=f"Slots: {mch('channel_slots')}\nFlip: {mch('channel_flip')}\nPFC: {mch('channel_pfc')}\nBJ: {mch('channel_blackjack')}\n"
            f"_Fallback global_: {ch_c.mention if ch_c else '—'}",
            inline=False,
        )
        embed.add_field(name="📊 Leaderboard (+casinolb)", value=mch("channel_leaderboard"), inline=True)
        embed.add_field(name="🤝 Trade (+trade)", value=mch("channel_trade"), inline=True)
        embed.add_field(name="🏷️ Enchères (+sellrole)", value=ch_a.mention if ch_a else "Non défini", inline=True)
        embed.add_field(name="Jeux ON/OFF", value=gtxt, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="casinopanel")
    @commands.has_permissions(administrator=True)
    async def casinopanel(self, ctx):
        view = CasinoConfigView()
        embed = discord.Embed(
            title="🎛️ Panneau casino (admin)",
            description="**Bouton 1** — Liste des commandes `+casinoset`\n"
            "**Bouton 2** — Activer / désactiver tout le casino\n"
            "**Bouton 3** — Rappel salons\n"
            "**Bouton 4** — Rappel taxe & limites\n\n"
            "Pour les valeurs précises, utilisez les commandes texte (ex. `+casinoset minbet 100`).",
            color=await get_guild_color(ctx.guild.id),
        )
        await ctx.send(embed=embed, view=view)

    @commands.group(name="casinoset", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def casinoset(self, ctx):
        await ctx.send(embed=error_embed(
            "Casino",
            "`settradechannel` · `setchannel` (slots flip pfc blackjack lb trade global encheres) · "
            "`minbet` `maxbet` `cooldown` `daily` `fee` `auctionfee` `bidinc` `game` · "
            "`chslots` `chflip` `chpfc` `chbj` `chleaderboard` `chtrade` · "
            "`auctionchannel` `casinochannel` `resetcasinochannel` `resetchannels`",
        ))

    @casinoset.command(name="minbet")
    async def cs_minbet(self, ctx, n: int):
        await update_casino_config(ctx.guild.id, {"min_bet": max(1, n)})
        await ctx.send(embed=success_embed("Casino", f"Mise min : **{n}**", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="maxbet")
    async def cs_maxbet(self, ctx, n: int):
        await update_casino_config(ctx.guild.id, {"max_bet": max(1, n)})
        await ctx.send(embed=success_embed("Casino", f"Mise max : **{n}**", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="cooldown")
    async def cs_cd(self, ctx, s: int):
        await update_casino_config(ctx.guild.id, {"cooldown_seconds": max(0, s)})
        await ctx.send(embed=success_embed("Casino", f"Cooldown : **{s}s**", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="daily")
    async def cs_daily(self, ctx, n: int):
        await update_casino_config(ctx.guild.id, {"daily_game_limit": max(1, n)})
        await ctx.send(embed=success_embed("Casino", f"Limite : **{n}** parties/jour", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="fee")
    async def cs_fee(self, ctx, p: int):
        p = max(0, min(50, p))
        await update_casino_config(ctx.guild.id, {"house_fee_percent": p})
        await ctx.send(embed=success_embed("Casino", f"Taxe sur gains : **{p}%**", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="auctionfee")
    async def cs_afee(self, ctx, p: int):
        p = max(0, min(30, p))
        await update_casino_config(ctx.guild.id, {"auction_fee_percent": p})
        await ctx.send(embed=success_embed("Casino", f"Frais dépôt vente : **{p}%**", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="bidinc")
    async def cs_bid(self, ctx, n: int):
        await update_casino_config(ctx.guild.id, {"bid_increment_min": max(1, n)})
        await ctx.send(embed=success_embed("Casino", f"Enchère min. par clic : **{n}**", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="lastgames")
    async def cs_lastgames(self, ctx, channel: discord.TextChannel = None):
        """Définit le salon du message 'Dernières parties' (sans salon = reset)."""
        if channel is None:
            await update_casino_config(ctx.guild.id, {"last_games_channel_id": None, "last_games_message_id": None})
            return await ctx.send(embed=success_embed("Casino", "Dernières parties : désactivé.", await get_guild_color(ctx.guild.id)))
        await update_casino_config(ctx.guild.id, {"last_games_channel_id": channel.id, "last_games_message_id": None})
        await ctx.send(embed=success_embed("Casino", f"Dernières parties → {channel.mention}", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="auctionchannel")
    async def cs_auch(self, ctx, channel: discord.TextChannel):
        await update_casino_config(ctx.guild.id, {"auction_channel_id": channel.id})
        await ctx.send(embed=success_embed("Casino", f"Salon enchères : {channel.mention}", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="casinochannel")
    async def cs_casch(self, ctx, channel: discord.TextChannel):
        await update_casino_config(ctx.guild.id, {"casino_channel_id": channel.id})
        await ctx.send(embed=success_embed("Casino", f"Salon casino : {channel.mention}", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="resetcasinochannel")
    async def cs_casch_reset(self, ctx):
        await update_casino_config(ctx.guild.id, {"casino_channel_id": None})
        await ctx.send(embed=success_embed("Casino", "Salon casino **global** désactivé (jeux partout si pas de salon par jeu).", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="resetchannels")
    async def cs_resetchannels(self, ctx):
        await update_casino_config(ctx.guild.id, {
            "casino_channel_id": None,
            "channel_slots": None,
            "channel_flip": None,
            "channel_pfc": None,
            "channel_blackjack": None,
            "channel_leaderboard": None,
            "channel_trade": None,
        })
        await ctx.send(embed=success_embed("Casino", "Tous les salons **jeux / lb / trade** réinitialisés (partout). Les enchères ne sont pas touchées.", await get_guild_color(ctx.guild.id)))

    @casinoset.group(name="setchannel", aliases=["setch", "ch"], invoke_without_command=True)
    async def sc_setchannel(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send(embed=error_embed(
                "Setchannel",
                "Un salon **par type** (sans #salon = reset ce type) :\n"
                "`slots` · `flip` · `pfc` · `blackjack` (alias `bj`) · `leaderboard` (alias `lb`) · "
                "`trade` · `global` (fallback casino) · `encheres`\n"
                "Ex. : `+casinoset setchannel slots #machine-a-sous`",
            ))

    @sc_setchannel.command(name="slots")
    async def scsch_slots(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_slots", channel)

    @sc_setchannel.command(name="flip")
    async def scsch_flip(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_flip", channel)

    @sc_setchannel.command(name="pfc")
    async def scsch_pfc(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_pfc", channel)

    @sc_setchannel.command(name="blackjack", aliases=["bj"])
    async def scsch_bj(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_blackjack", channel)

    @sc_setchannel.command(name="leaderboard", aliases=["lb"])
    async def scsch_lb(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_leaderboard", channel)

    @sc_setchannel.command(name="trade")
    async def scsch_trade(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_trade", channel)

    @sc_setchannel.command(name="global")
    async def scsch_global(self, ctx, channel: discord.TextChannel = None):
        await update_casino_config(ctx.guild.id, {"casino_channel_id": channel.id if channel else None})
        col = await get_guild_color(ctx.guild.id)
        if channel:
            await ctx.send(embed=success_embed("Casino", f"Salon **global** (fallback) : {channel.mention}", col))
        else:
            await ctx.send(embed=success_embed("Casino", "Salon global désactivé.", col))

    @sc_setchannel.command(name="encheres")
    async def scsch_enc(self, ctx, channel: discord.TextChannel = None):
        await update_casino_config(ctx.guild.id, {"auction_channel_id": channel.id if channel else None})
        col = await get_guild_color(ctx.guild.id)
        if channel:
            await ctx.send(embed=success_embed("Casino", f"Salon **enchères** : {channel.mention}", col))
        else:
            await ctx.send(embed=success_embed("Casino", "Salon enchères désactivé.", col))

    async def _set_ch(self, ctx, key: str, channel: Optional[discord.TextChannel]):
        await update_casino_config(ctx.guild.id, {key: channel.id if channel else None})
        if channel:
            await ctx.send(embed=success_embed("Casino", f"{key} → {channel.mention}", await get_guild_color(ctx.guild.id)))
        else:
            await ctx.send(embed=success_embed("Casino", f"{key} désactivé (partout ou fallback).", await get_guild_color(ctx.guild.id)))

    @casinoset.command(name="chslots")
    async def cs_chslots(self, ctx, channel: discord.TextChannel = None):
        """Salon dédié +casino slots (sans salon = reset ce jeu)"""
        await self._set_ch(ctx, "channel_slots", channel)

    @casinoset.command(name="chflip")
    async def cs_chflip(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_flip", channel)

    @casinoset.command(name="chpfc")
    async def cs_chpfc(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_pfc", channel)

    @casinoset.command(name="chbj")
    async def cs_chbj(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_blackjack", channel)

    @casinoset.command(name="chleaderboard")
    async def cs_chlb(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_leaderboard", channel)

    @casinoset.command(name="chtrade")
    async def cs_chtrade(self, ctx, channel: discord.TextChannel = None):
        await self._set_ch(ctx, "channel_trade", channel)

    @casinoset.command(name="game")
    async def cs_game(self, ctx, name: str, state: str):
        name = name.lower()
        st = state.lower() in ("on", "1", "true", "oui", "yes")
        cfg = await get_casino_config(ctx.guild.id)
        games = dict(cfg.get("games", DEFAULT_CASINO["games"]))
        if name not in games:
            return await ctx.send(embed=error_embed("Casino", f"Jeu inconnu : {name} (slots, flip, blackjack, pfc)"))
        games[name] = st
        await update_casino_config(ctx.guild.id, {"games": games})
        await ctx.send(embed=success_embed("Casino", f"**{name}** → {'ON' if st else 'OFF'}", await get_guild_color(ctx.guild.id)))

    @commands.command(name="casinolb", aliases=["casinoleaderboard"])
    async def casinolb(self, ctx):
        cfg = await get_casino_config(ctx.guild.id)
        err = await _must_be_channel(ctx, cfg, "channel_leaderboard")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        col = get_collection("casino_stats")
        if col is None:
            return await ctx.send(embed=error_embed("DB", "Erreur."))
        pipeline = [
            {"$match": {"guild_id": str(ctx.guild.id)}},
            {"$sort": {"net": -1}},
            {"$limit": 10},
        ]
        lines = []
        i = 1
        async for doc in col.aggregate(pipeline):
            uid = doc.get("user_id")
            net = doc.get("net", 0)
            u = self.bot.get_user(int(uid))
            name = u.display_name if u else f"ID {uid}"
            lines.append(f"**{i}.** {name} — **{net:+,}** net")
            i += 1
        color = await get_guild_color(ctx.guild.id)
        embed = discord.Embed(
            title="🏆 Leaderboard casino (net)",
            description="\n".join(lines) if lines else "Pas encore de données.",
            color=color,
        )
        await ctx.send(embed=embed)

    @commands.command(name="casinostats")
    async def casinostats(self, ctx, member: discord.Member = None):
        cfg = await get_casino_config(ctx.guild.id)
        err = await _must_be_channel(ctx, cfg, "channel_leaderboard")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        member = member or ctx.author
        col = get_collection("casino_stats")
        if col is None:
            return await ctx.send(embed=error_embed("DB", "Erreur."))
        doc = await col.find_one({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
        w = doc.get("wagered", 0) if doc else 0
        won = doc.get("won", 0) if doc else 0
        net = doc.get("net", 0) if doc else 0
        g = doc.get("games", 0) if doc else 0
        color = await get_guild_color(ctx.guild.id)
        embed = discord.Embed(title=f"📊 Stats casino — {member.display_name}", color=color)
        embed.add_field(name="Total misé", value=f"{w:,}", inline=True)
        embed.add_field(name="Total gagné (après taxe)", value=f"{won:,}", inline=True)
        embed.add_field(name="Net", value=f"{net:+,}", inline=True)
        embed.add_field(name="Parties", value=str(g), inline=True)
        # Progression vers le prochain rank casino (net + parties)
        await self._ranks_ensure_defaults(ctx.guild.id)
        rcfg = await get_casino_ranks_config(ctx.guild.id)
        ranks = rcfg.get("ranks") or []
        if rcfg.get("enabled") and ranks and len(ranks) >= 2:
            idx = _casino_best_rank_index(ranks, net=int(net), games=int(g))
            if idx < len(ranks) - 1:
                nxt = ranks[idx + 1]
                need_net_total = max(1, int(nxt.get("req_net", 0)))
                need_games_total = max(1, int(nxt.get("req_games", 0)))
                p_net = min(1.0, max(0.0, (int(net) / need_net_total)))
                p_games = min(1.0, max(0.0, (int(g) / need_games_total)))
                # % global = le plus lent des deux (il faut valider net ET parties)
                p = min(p_net, p_games)
                bar = get_progress_bar(int(p * 100), 100, length=18)
                need_net = max(0, need_net_total - int(net))
                need_games = max(0, need_games_total - int(g))
                embed.add_field(
                    name="🏆 Progression vers le prochain rang",
                    value=f"{bar}\nManque : net **{need_net:,}** · parties **{need_games:,}**",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="🏆 Rang",
                    value="Tu es au **rang maximum**.",
                    inline=False,
                )
        await ctx.send(embed=embed)

    @commands.group(name="casino", invoke_without_command=True)
    async def casino_group(self, ctx):
        embed = discord.Embed(
            title="🎰 Casino",
            description="`+casino slots [mise]` · `+casino flip [mise] pile` · `+casino pfc [mise] pierre` · `+casino blackjack [mise]`\n`+helpcasino` pour tout le détail.",
            color=await get_guild_color(ctx.guild.id),
        )
        await ctx.send(embed=embed)

    @casino_group.command(name="slots")
    async def c_slots(self, ctx, mise: int):
        cfg = await get_casino_config(ctx.guild.id)
        err = await validate_bet(ctx, mise, "slots")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        if not await remove_coins(ctx.guild.id, ctx.author.id, mise):
            return await ctx.send(embed=error_embed("Casino", "Solde insuffisant."))
        await after_bet_ok(ctx, "slots")
        bonus = await get_member_casino_rank_bonus(ctx.guild, ctx.author)
        luck = max(0.0, float(bonus.get("slots_luck", 0.0)))
        symbols = ["🍒", "🍋", "🍊", "💎", "7️⃣"]
        # Luck: augmente légèrement la proba de 💎 et 7️⃣ sans casser l'économie
        w = [1.0, 1.0, 1.0, 0.6 + (luck * 6.0), 0.35 + (luck * 6.0)]
        a, b, c = random.choices(symbols, weights=w, k=3)
        mult = 0
        if a == b == c:
            mult = 10 if a == "7️⃣" else 8
        elif a == b or b == c or a == c:
            mult = 2
        gross = mise * mult if mult else 0
        net = await take_house_fee(gross, cfg["house_fee_percent"])
        net = apply_rank_win_bonus(net, int(bonus.get("win_bonus_pct", 0)))
        if net:
            await add_coins(ctx.guild.id, ctx.author.id, net)
        await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=net)
        await self._ranks_autosync_member(ctx.author)
        try:
            await _update_last_games_message(
                ctx.guild,
                f"<t:{int(datetime.now(timezone.utc).timestamp())}:t> 🎰 {ctx.author.mention} mise **{mise}** → net **{net}**",
            )
        except Exception:
            pass
        conf = await get_guild_config(ctx.guild.id) or {}
        emoji = conf.get("currency_emoji", "💰")
        color = await get_guild_color(ctx.guild.id)
        desc = f"| {a} | {b} | {c} |\n\n"
        desc += "🎉 JACKPOT !" if mult >= 8 else "✅ Gain !" if mult else "😢 Perdu"
        embed = discord.Embed(title="🎰 Slots", description=desc + f"\nMise **{mise}** → Net **{net}** {emoji}", color=color)
        await ctx.send(embed=embed)

    @casino_group.command(name="flip")
    async def c_flip(self, ctx, mise: int, choix: str):
        cfg = await get_casino_config(ctx.guild.id)
        err = await validate_bet(ctx, mise, "flip")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        choix = choix.lower()
        if choix not in ("pile", "face"):
            return await ctx.send(embed=error_embed("Casino", "Choix : pile ou face"))
        if not await remove_coins(ctx.guild.id, ctx.author.id, mise):
            return await ctx.send(embed=error_embed("Casino", "Solde insuffisant."))
        await after_bet_ok(ctx, "flip")
        bonus = await get_member_casino_rank_bonus(ctx.guild, ctx.author)
        luck = max(0.0, float(bonus.get("flip_luck", 0.0)))
        if luck and random.random() < luck:
            result = choix
        else:
            result = random.choice(["pile", "face"])
        win = choix == result
        gross = mise * 2 if win else 0
        net = await take_house_fee(gross, cfg["house_fee_percent"]) if win else 0
        net = apply_rank_win_bonus(net, int(bonus.get("win_bonus_pct", 0))) if win else 0
        if net:
            await add_coins(ctx.guild.id, ctx.author.id, net)
        await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=net)
        await self._ranks_autosync_member(ctx.author)
        try:
            await _update_last_games_message(
                ctx.guild,
                f"<t:{int(datetime.now(timezone.utc).timestamp())}:t> 🪙 {ctx.author.mention} mise **{mise}** → net **{net}**",
            )
        except Exception:
            pass
        conf = await get_guild_config(ctx.guild.id) or {}
        color = await get_guild_color(ctx.guild.id)
        embed = discord.Embed(
            title="🪙 Pile ou face",
            description=f"**{result}** — {'Gagné' if win else 'Perdu'} — Net **{net}** {conf.get('currency_emoji', '💰')}",
            color=color,
        )
        await ctx.send(embed=embed)

    @casino_group.command(name="pfc")
    async def c_pfc(self, ctx, mise: int, choix: str):
        cfg = await get_casino_config(ctx.guild.id)
        err = await validate_bet(ctx, mise, "pfc")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        PFC = {"pierre": "🪨", "feuille": "📄", "ciseaux": "✂️"}
        choix = choix.lower().strip()
        if choix not in PFC:
            return await ctx.send(embed=error_embed("Casino", "pierre, feuille ou ciseaux"))
        if not await remove_coins(ctx.guild.id, ctx.author.id, mise):
            return await ctx.send(embed=error_embed("Casino", "Solde insuffisant."))
        await after_bet_ok(ctx, "pfc")
        bonus = await get_member_casino_rank_bonus(ctx.guild, ctx.author)
        luck = max(0.0, float(bonus.get("pfc_luck", 0.0)))
        wins = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}
        if luck and random.random() < luck:
            # bot choisit le coup qui perd contre le joueur
            bot_c = wins[choix]
        else:
            bot_c = random.choice(list(PFC.keys()))
        if choix == bot_c:
            await add_coins(ctx.guild.id, ctx.author.id, mise)
            net = 0
            # Égalité = mise rendue : profit 0
            await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=mise)
            msg = "Égalité — mise rendue"
        elif wins[choix] == bot_c:
            gross = mise * 2
            net = await take_house_fee(gross, cfg["house_fee_percent"])
            net = apply_rank_win_bonus(net, int(bonus.get("win_bonus_pct", 0)))
            await add_coins(ctx.guild.id, ctx.author.id, net)
            await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=net)
            msg = "Victoire"
        else:
            net = 0
            await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=0)
            msg = "Défaite"
        await self._ranks_autosync_member(ctx.author)
        try:
            await _update_last_games_message(
                ctx.guild,
                f"<t:{int(datetime.now(timezone.utc).timestamp())}:t> ✂️ {ctx.author.mention} mise **{mise}** → {msg} (net **{net}**)",
            )
        except Exception:
            pass
        conf = await get_guild_config(ctx.guild.id) or {}
        color = await get_guild_color(ctx.guild.id)
        embed = discord.Embed(
            title="🪨 PFC",
            description=f"{PFC[choix]} vs {PFC[bot_c]} — **{msg}** — Net **{net}** {conf.get('currency_emoji', '💰')}",
            color=color,
        )
        await ctx.send(embed=embed)

    @casino_group.command(name="blackjack")
    async def c_bj(self, ctx, mise: int):
        cfg = await get_casino_config(ctx.guild.id)
        err = await validate_bet(ctx, mise, "blackjack")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        if not await remove_coins(ctx.guild.id, ctx.author.id, mise):
            return await ctx.send(embed=error_embed("Casino", "Solde insuffisant."))
        await after_bet_ok(ctx, "blackjack")

        deck = list("234567890JQKA" * 4)
        random.shuffle(deck)

        def val(c):
            if c in "JQK0":
                return 10
            if c == "A":
                return 11
            return int(c)

        def hand_value(cards):
            v = sum(val(c) for c in cards)
            aces = cards.count("A")
            while v > 21 and aces > 0:
                v -= 10
                aces -= 1
            return v

        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        gid = ctx.guild.id
        uid = ctx.author.id
        fee = cfg["house_fee_percent"]

        class CBJ(View):
            def __init__(self):
                super().__init__(timeout=60)
                self.player = player
                self.dealer = dealer
                self.deck = deck

            async def finish_loss(self, interaction):
                await inc_casino_stat(gid, uid, wagered=mise, won=0)
                cog = interaction.client.get_cog("CasinoCog")
                if cog and isinstance(interaction.user, discord.Member):
                    await cog._ranks_autosync_member(interaction.user)
                    try:
                        await _update_last_games_message(
                            interaction.guild,
                            f"<t:{int(datetime.now(timezone.utc).timestamp())}:t> 🃏 {interaction.user.mention} mise **{mise}** → Bust (net **0**)",
                        )
                    except Exception:
                        pass
                for c in self.children:
                    c.disabled = True
                await interaction.response.edit_message(embed=discord.Embed(title="🃏 Blackjack", description="Bust — perdu.", color=0xED4245), view=self)

            @discord.ui.button(label="Tirer", style=discord.ButtonStyle.primary)
            async def hit(self, interaction: discord.Interaction, btn: Button):
                if interaction.user.id != uid:
                    await interaction.response.send_message("Pas votre partie.", ephemeral=True)
                    return
                self.player.append(self.deck.pop())
                pv = hand_value(self.player)
                if pv > 21:
                    await self.finish_loss(interaction)
                    return
                clr = await get_guild_color(gid)
                await interaction.response.edit_message(
                    embed=discord.Embed(title="🃏 Blackjack", description=f"Vous: {self.player} ({pv})\nCroupier: {self.dealer[0]} ?", color=clr),
                    view=self,
                )

            @discord.ui.button(label="Rester", style=discord.ButtonStyle.secondary)
            async def stay(self, interaction: discord.Interaction, btn: Button):
                if interaction.user.id != uid:
                    await interaction.response.send_message("Pas votre partie.", ephemeral=True)
                    return
                for c in self.children:
                    c.disabled = True
                while hand_value(self.dealer) < 17:
                    self.dealer.append(self.deck.pop())
                pv, dv = hand_value(self.player), hand_value(self.dealer)
                bonus = await get_member_casino_rank_bonus(interaction.guild, interaction.user)
                net = 0
                if dv > 21 or pv > dv:
                    gross = mise * 2
                    net = await take_house_fee(gross, fee)
                    net = apply_rank_win_bonus(net, int(bonus.get("win_bonus_pct", 0)))
                    await add_coins(gid, uid, net)
                elif pv == dv:
                    await add_coins(gid, uid, mise)
                    net = mise
                await inc_casino_stat(gid, uid, wagered=mise, won=net)
                cog = interaction.client.get_cog("CasinoCog")
                if cog and isinstance(interaction.user, discord.Member):
                    await cog._ranks_autosync_member(interaction.user)
                    try:
                        await _update_last_games_message(
                            interaction.guild,
                            f"<t:{int(datetime.now(timezone.utc).timestamp())}:t> 🃏 {interaction.user.mention} mise **{mise}** → net **{net}**",
                        )
                    except Exception:
                        pass
                clr = 0x57F287 if pv > dv or dv > 21 else 0x5865F2 if pv == dv else 0xED4245
                await interaction.response.edit_message(
                    embed=discord.Embed(title="🃏 Blackjack", description=f"Vous: {self.player} ({pv})\nCroupier: {self.dealer} ({dv})\n**Net: {net}**", color=clr),
                    view=self,
                )

        v = CBJ()
        clr = await get_guild_color(gid)
        await ctx.send(
            embed=discord.Embed(title="🃏 Blackjack", description=f"Mise **{mise}**\nVous: {player} ({hand_value(player)})\nCroupier: {dealer[0]} ?", color=clr),
            view=v,
        )

    @commands.command(name="sellrole")
    async def sellrole(self, ctx, role: discord.Role, prix: int, buyout: int = None):
        cfg = await get_casino_config(ctx.guild.id)
        ach = cfg.get("auction_channel_id")
        if not ach:
            return await ctx.send(embed=error_embed("Enchères", "Définissez `+casinoset auctionchannel #salon`."))
        ch = ctx.guild.get_channel(ach)
        if not ch:
            return await ctx.send(embed=error_embed("Enchères", "Salon enchères introuvable."))
        if ctx.channel.id != ach:
            return await ctx.send(embed=error_embed("Enchères", f"Utilisez la commande dans {ch.mention}."))
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Enchères", "Le bot ne peut pas gérer ce rôle."))
        if role.managed:
            return await ctx.send(embed=error_embed("Enchères", "Rôle intégration / bot — interdit."))
        if role not in ctx.author.roles:
            return await ctx.send(embed=error_embed("Enchères", "Vous devez **posséder** le rôle pour le vendre."))
        if prix < 1:
            return await ctx.send(embed=error_embed("Enchères", "Prix invalide."))
        fee_pct = max(0, min(30, int(cfg.get("auction_fee_percent", 0))))
        fee = int(prix * fee_pct / 100) if fee_pct else 0
        if fee > 0 and not await remove_coins(ctx.guild.id, ctx.author.id, fee):
            return await ctx.send(embed=error_embed("Enchères", f"Frais de dépôt : **{fee}** SayuCoins requis."))
        aid = str(uuid.uuid4())[:12]
        col = get_collection("role_auctions")
        ends = datetime.now(timezone.utc) + timedelta(hours=48)
        await col.insert_one({
            "_id": aid,
            "guild_id": str(ctx.guild.id),
            "role_id": str(role.id),
            "seller_id": str(ctx.author.id),
            "current_bid": prix,
            "current_bidder_id": None,
            "buyout": buyout,
            "channel_id": str(ch.id),
            "ends_at": ends,
            "status": "active",
            "thread_id": None,
            "join_message_id": None,
        })
        emb = discord.Embed(
            title=f"🏷️ Enchère — {role.name}",
            description=f"Vendeur: {ctx.author.mention}\nPrix de départ: **{prix}**\n"
            f"{f'**Achat immédiat :** {buyout} SC — le **vendeur** valide avec `+auctionbuyout {aid} @acheteur`\n' if buyout else ''}"
            f"Fin: <t:{int(ends.timestamp())}:R>\n`ID: {aid}`",
            color=await get_guild_color(ctx.guild.id),
        )
        view = AuctionBidView(aid)
        color = await get_guild_color(ctx.guild.id)
        try:
            tname = f"Enchère {role.name}"[:90]
            thread = await _create_private_thread(ch, tname)
            await _thread_add_user_safe(thread, ctx.author)
            msg = await thread.send(embed=emb, view=view)
            self.bot.add_view(view)
            join_emb = discord.Embed(
                title=f"🏷️ Enchère — {role.name}",
                description=f"Fil **privé** : seuls les membres qui rejoignent peuvent voir les boutons d’enchère.\n"
                f"Prix de départ : **{prix}** SayuCoins\n"
                f"{f'Achat immédiat : **{buyout}** SC — le vendeur : `+auctionbuyout {aid} @acheteur`\n' if buyout else ''}"
                f"`ID: {aid}`",
                color=color,
            )
            jv = AuctionJoinView(aid)
            jmsg = await ch.send(embed=join_emb, view=jv)
            self.bot.add_view(jv)
            await col.update_one(
                {"_id": aid},
                {"$set": {
                    "message_id": str(msg.id),
                    "thread_id": str(thread.id),
                    "join_message_id": str(jmsg.id),
                }},
            )
            await ctx.send(
                embed=success_embed(
                    "Enchères",
                    f"Vente dans le fil privé {thread.mention} — annonce + bouton **Rejoindre** dans {ch.mention}.",
                    color,
                )
            )
        except (TypeError, discord.HTTPException) as e:
            msg = await ch.send(embed=emb, view=view)
            self.bot.add_view(view)
            await col.update_one({"_id": aid}, {"$set": {"message_id": str(msg.id)}})
            hint = ""
            if isinstance(e, discord.HTTPException):
                hint = " (fil privé impossible — vérifie **Fils privés** du serveur et la permission **Gérer les fils** du bot)"
            await ctx.send(
                embed=success_embed(
                    "Enchères",
                    f"Vente créée dans {ch.mention} (mode salon public{hint}).",
                    color,
                )
            )

    @commands.command(name="auctioncancel")
    async def auction_cancel(self, ctx, auction_id: str):
        cfg = await get_casino_config(ctx.guild.id)
        ach = cfg.get("auction_channel_id")
        if ach and ctx.channel.id != ach:
            ch = ctx.guild.get_channel(ach)
            if ch:
                return await ctx.send(embed=error_embed("Enchères", f"Utilisez {ch.mention}."))
        col = get_collection("role_auctions")
        doc = await col.find_one({"_id": auction_id, "guild_id": str(ctx.guild.id)})
        if not doc:
            return await ctx.send(embed=error_embed("Enchères", "ID introuvable."))
        if str(ctx.author.id) != doc["seller_id"] and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=error_embed("Enchères", "Pas votre enchère."))
        await col.update_one({"_id": auction_id}, {"$set": {"status": "cancelled"}})
        tid = doc.get("thread_id")
        if tid:
            t = ctx.guild.get_thread(int(tid))
            if t:
                try:
                    await t.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass
        jmid = doc.get("join_message_id")
        if jmid and ach:
            parent = ctx.guild.get_channel(ach)
            if isinstance(parent, discord.TextChannel):
                try:
                    jm = await parent.fetch_message(int(jmid))
                    await jm.delete()
                except Exception:
                    pass
        await ctx.send(embed=success_embed("Enchères", "Enchère annulée.", await get_guild_color(ctx.guild.id)))

    @commands.command(name="settradechannel", aliases=["setchanneltrade", "salontrade", "tradechannel"])
    @commands.has_permissions(administrator=True)
    async def settradechannel(self, ctx, channel: discord.TextChannel = None):
        """Définit le salon où +trade est autorisé (sans salon = partout). Même effet que +casinoset chtrade."""
        await self._set_ch(ctx, "channel_trade", channel)

    @commands.command(name="setrankcasino", aliases=["setcasinorank", "setrankscasino"])
    @commands.has_permissions(administrator=True)
    async def setrankcasino(self, ctx, channel: discord.TextChannel = None):
        """Définit le salon où le panel ranks casino est posté (sans salon = reset)."""
        if channel is None:
            await update_casino_ranks_config(ctx.guild.id, {"rank_channel_id": None, "panel_message_id": None})
            return await ctx.send(embed=success_embed("Ranks Casino", "Salon ranks reset (partout).", await get_guild_color(ctx.guild.id)))
        await update_casino_ranks_config(ctx.guild.id, {"rank_channel_id": str(channel.id)})
        await ctx.send(embed=success_embed("Ranks Casino", f"Salon ranks : {channel.mention}", await get_guild_color(ctx.guild.id)))

    @commands.group(name="casinoranks", aliases=["rankcasino", "rankscasino"], invoke_without_command=True)
    async def casinoranks(self, ctx):
        color = await get_guild_color(ctx.guild.id)
        cfg = await get_casino_ranks_config(ctx.guild.id)
        on = cfg.get("enabled", False)
        ch = ctx.guild.get_channel(int(cfg["rank_channel_id"])) if cfg.get("rank_channel_id") else None
        emb = discord.Embed(title="🏆 Ranks Casino — commandes", color=color)
        emb.add_field(name="Statut", value="✅ Activé" if on else "❌ Désactivé", inline=True)
        emb.add_field(name="Salon panel", value=ch.mention if ch else "—", inline=True)
        emb.add_field(
            name="Joueurs",
            value="`+casinoranks me` — ton rang, bonus, progression",
            inline=False,
        )
        emb.add_field(
            name="Admin",
            value="`+casinoranks setup` — crée les 12 rôles + hiérarchie\n"
            "`+casinoranks panel` — poste/maj le panel\n"
            "`+casinoranks sync [@membre]` — attribue les rangs selon net + parties\n"
            "`+casinoranks setreq [index] [net] [parties]` — modifie un palier\n"
            "`+setrankcasino #salon` — définit le salon panel",
            inline=False,
        )
        await ctx.send(embed=emb)

    async def _ranks_ensure_defaults(self, gid: int):
        cfg = await get_casino_ranks_config(gid)
        if not cfg.get("ranks"):
            await update_casino_ranks_config(
                gid,
                {
                    "enabled": True,
                    "ranks": [
                        {
                            "emoji": r["emoji"],
                            "name": r["name"],
                            "color": r["color"],
                            "role_id": None,
                            "req_net": r["req_net"],
                            "req_games": r["req_games"],
                            "bonus": r["bonus"],
                        }
                        for r in DEFAULT_CASINO_RANKS
                    ],
                },
            )

    async def _ranks_autosync_member(self, member: discord.Member):
        """Assigne automatiquement le bon rôle casino à un membre (si activé)."""
        cfg = await get_casino_ranks_config(member.guild.id)
        if not cfg.get("enabled"):
            return
        ranks = cfg.get("ranks") or []
        if not ranks:
            return
        if not all(r.get("role_id") for r in ranks):
            return
        net, games = await _casino_get_user_net_games(member.guild.id, member.id)
        idx = _casino_best_rank_index(ranks, net=net, games=games)
        want = member.guild.get_role(int(ranks[idx]["role_id"]))
        if not want:
            return
        role_ids = {int(r["role_id"]) for r in ranks if r.get("role_id")}
        to_remove = [r for r in member.roles if r.id in role_ids and r.id != want.id]
        try:
            if to_remove:
                await member.remove_roles(*to_remove, reason="Auto ranks casino")
            if want not in member.roles:
                await member.add_roles(want, reason="Auto ranks casino")
        except discord.HTTPException:
            return

    @casinoranks.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def casinoranks_setup(self, ctx):
        """Crée les rôles casino (emoji | nom) et les place en hiérarchie."""
        await self._ranks_ensure_defaults(ctx.guild.id)
        cfg = await get_casino_ranks_config(ctx.guild.id)
        ranks = cfg.get("ranks") or []
        if not ranks:
            return await ctx.send(embed=error_embed("Ranks Casino", "Config introuvable."))
        bot_me = ctx.guild.me
        created = 0
        updated = 0
        for r in ranks:
            rname = f"{r.get('emoji','🎲')} | {r.get('name','Casino')}"
            rid = r.get("role_id")
            role_obj = ctx.guild.get_role(int(rid)) if rid else None
            if role_obj is None:
                try:
                    role_obj = await ctx.guild.create_role(
                        name=rname[:100],
                        colour=discord.Colour(int(r.get("color", 0x2F3136))),
                        mentionable=False,
                        hoist=False,
                        reason="Setup ranks casino",
                    )
                    created += 1
                except discord.HTTPException as e:
                    return await ctx.send(embed=error_embed("Ranks Casino", f"Erreur création rôle : {e}"))
                await update_casino_ranks_config(ctx.guild.id, {f"ranks.{ranks.index(r)}.role_id": str(role_obj.id)})
                r["role_id"] = str(role_obj.id)
            else:
                try:
                    await role_obj.edit(
                        name=rname[:100],
                        colour=discord.Colour(int(r.get("color", role_obj.colour.value))),
                        reason="Maj ranks casino",
                    )
                    updated += 1
                except discord.HTTPException:
                    pass
            if role_obj >= bot_me.top_role:
                return await ctx.send(embed=error_embed("Ranks Casino", f"Le rôle {role_obj.mention} est au-dessus du bot. Descends le rôle du bot."))  # noqa: E501

        # Positionnement: on met le rang le plus haut au-dessus des autres (mais sous le bot)
        try:
            base = bot_me.top_role.position - 1
            desired = {}
            # ranks[0] = débutant en bas, ranks[-1] en haut
            for i, r in enumerate(ranks):
                role_obj = ctx.guild.get_role(int(r["role_id"]))
                if role_obj:
                    desired[role_obj] = max(1, base - (len(ranks) - 1 - i))
            await ctx.guild.edit_role_positions(positions=desired)
        except discord.HTTPException:
            pass

        await update_casino_ranks_config(ctx.guild.id, {"enabled": True})
        await ctx.send(embed=success_embed("Ranks Casino", f"✅ Setup terminé. Créés: {created} · MAJ: {updated}", await get_guild_color(ctx.guild.id)))

    def _ranks_panel_embed(self, guild: discord.Guild, cfg: dict, *, net: int = 0, games: int = 0) -> discord.Embed:
        color = 0xF1C40F
        ranks = cfg.get("ranks") or []
        lines = []
        for i, r in enumerate(ranks):
            emoji = r.get("emoji", "🎲")
            name = r.get("name", "Casino")
            rn = int(r.get("req_net", 0))
            rg = int(r.get("req_games", 0))
            rid = r.get("role_id")
            ro = guild.get_role(int(rid)) if rid else None
            tag = ro.mention if ro else f"`{emoji} | {name}`"
            lines.append(f"**{i}.** {tag} — net ≥ **{rn:,}** · parties ≥ **{rg:,}**")
        emb = discord.Embed(
            title="🏆 Ranks Casino — progression",
            description="\n".join(lines[:12]) if lines else "Setup requis : `+casinoranks setup`",
            color=color,
        )
        if ranks:
            idx = _casino_best_rank_index(ranks, net=net, games=games)
            emb.set_footer(text=f"Ton net: {net:+,} · Tes parties: {games:,} · Rang actuel estimé: #{idx}")
        return emb

    @casinoranks.command(name="panel")
    @commands.has_permissions(administrator=True)
    async def casinoranks_panel(self, ctx):
        await self._ranks_ensure_defaults(ctx.guild.id)
        cfg = await get_casino_ranks_config(ctx.guild.id)
        ch_id = cfg.get("rank_channel_id")
        if not ch_id:
            return await ctx.send(embed=error_embed("Ranks Casino", "Définis le salon avec `+setrankcasino #salon`."))
        ch = ctx.guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel):
            return await ctx.send(embed=error_embed("Ranks Casino", "Salon introuvable."))
        emb = self._ranks_panel_embed(ctx.guild, cfg)
        mid = cfg.get("panel_message_id")
        if mid:
            try:
                m = await ch.fetch_message(int(mid))
                await m.edit(embed=emb, view=None)
                await ctx.send(embed=success_embed("Ranks Casino", f"Panel mis à jour : {ch.mention}", await get_guild_color(ctx.guild.id)))
                return
            except Exception:
                pass
        m = await ch.send(embed=emb)
        await update_casino_ranks_config(ctx.guild.id, {"panel_message_id": str(m.id), "enabled": True})
        await ctx.send(embed=success_embed("Ranks Casino", f"Panel posté : {m.jump_url}", await get_guild_color(ctx.guild.id)))

    @casinoranks.command(name="setreq")
    @commands.has_permissions(administrator=True)
    async def casinoranks_setreq(self, ctx, index: int, net: int, parties: int):
        await self._ranks_ensure_defaults(ctx.guild.id)
        cfg = await get_casino_ranks_config(ctx.guild.id)
        ranks = cfg.get("ranks") or []
        if index < 0 or index >= len(ranks):
            return await ctx.send(embed=error_embed("Ranks Casino", f"Index invalide (0–{max(0, len(ranks)-1)})."))
        ranks[index]["req_net"] = max(0, int(net))
        ranks[index]["req_games"] = max(0, int(parties))
        await update_casino_ranks_config(ctx.guild.id, {"ranks": ranks})
        await ctx.send(embed=success_embed("Ranks Casino", f"✅ Palier #{index} mis à jour.", await get_guild_color(ctx.guild.id)))

    @casinoranks.command(name="sync")
    @commands.has_permissions(administrator=True)
    async def casinoranks_sync(self, ctx, member: discord.Member = None):
        await self._ranks_ensure_defaults(ctx.guild.id)
        cfg = await get_casino_ranks_config(ctx.guild.id)
        ranks = cfg.get("ranks") or []
        if not ranks:
            return await ctx.send(embed=error_embed("Ranks Casino", "Setup requis."))
        role_ids = [int(r["role_id"]) for r in ranks if r.get("role_id")]
        if not role_ids or len(role_ids) != len(ranks):
            return await ctx.send(embed=error_embed("Ranks Casino", "Rôles manquants — lance `+casinoranks setup`."))

        targets = [member] if member else [m for m in ctx.guild.members if not m.bot]
        done = 0
        for m in targets:
            net, games = await _casino_get_user_net_games(ctx.guild.id, m.id)
            idx = _casino_best_rank_index(ranks, net=net, games=games)
            want = ctx.guild.get_role(int(ranks[idx]["role_id"]))
            if not want:
                continue
            to_remove = [r for r in m.roles if r.id in role_ids and r.id != want.id]
            try:
                if to_remove:
                    await m.remove_roles(*to_remove, reason="Sync ranks casino")
                if want not in m.roles:
                    await m.add_roles(want, reason="Sync ranks casino")
                done += 1
            except discord.HTTPException:
                continue
        await ctx.send(embed=success_embed("Ranks Casino", f"✅ Sync terminé : {done} membre(s).", await get_guild_color(ctx.guild.id)))

    @casinoranks.command(name="me")
    async def casinoranks_me(self, ctx):
        await self._ranks_ensure_defaults(ctx.guild.id)
        cfg = await get_casino_ranks_config(ctx.guild.id)
        ranks = cfg.get("ranks") or []
        net, games = await _casino_get_user_net_games(ctx.guild.id, ctx.author.id)
        idx = _casino_best_rank_index(ranks, net=net, games=games) if ranks else 0
        cur = ranks[idx] if ranks else None
        bonus = await get_member_casino_rank_bonus(ctx.guild, ctx.author)
        color = await get_guild_color(ctx.guild.id)
        emb = discord.Embed(title="🏆 Mon rang casino", color=color)
        if cur:
            rid = cur.get("role_id")
            ro = ctx.guild.get_role(int(rid)) if rid else None
            emb.add_field(name="Rang", value=(ro.mention if ro else f"{cur.get('emoji','🎲')} | {cur.get('name','') }"), inline=False)
        emb.add_field(name="Net", value=f"{net:+,}", inline=True)
        emb.add_field(name="Parties", value=f"{games:,}", inline=True)
        emb.add_field(
            name="Bonus actifs",
            value=f"Cooldown -{bonus['cooldown_minus']}s · Gain +{bonus['win_bonus_pct']}%\n"
            f"Luck: slots {bonus['slots_luck']*100:.1f}% · flip {bonus['flip_luck']*100:.1f}% · pfc {bonus['pfc_luck']*100:.1f}%",
            inline=False,
        )
        if ranks and idx < len(ranks) - 1:
            nxt = ranks[idx + 1]
            need_net = max(0, int(nxt.get("req_net", 0)) - net)
            need_games = max(0, int(nxt.get("req_games", 0)) - games)
            emb.add_field(
                name="Prochain rang",
                value=f"{nxt.get('emoji','⭐')} | {nxt.get('name','')}\n"
                f"Manque: net **{need_net:,}** · parties **{need_games:,}**",
                inline=False,
            )
        await ctx.send(embed=emb)

    @commands.command(name="hierarchie", aliases=["hierarchiecasino", "casinohierarchie"])
    async def hierarchie(self, ctx):
        """Affiche la hiérarchie casino (emoji | nom + descriptif) numérotée."""
        await self._ranks_ensure_defaults(ctx.guild.id)
        cfg = await get_casino_ranks_config(ctx.guild.id)
        ranks = cfg.get("ranks") or []
        if not ranks:
            return await ctx.send(embed=error_embed("Ranks Casino", "Setup requis : `+casinoranks setup`."))

        color = await get_guild_color(ctx.guild.id)
        emb = discord.Embed(
            title="🏆 Hiérarchie Casino",
            description="Progression basée sur : `net gagné` + `nombre de parties`.\n"
            "Index = rang (0 -> débutant, 11 -> divin).",
            color=color,
        )

        blocks = []
        for i, r in enumerate(ranks):
            emoji = r.get("emoji", "🎲")
            name = r.get("name", "Casino")
            desc = r.get("desc", "—")
            bonus = r.get("bonus") or {}
            cd = int(bonus.get("cooldown_minus", 0))
            win_pct = int(bonus.get("win_bonus_pct", 0))
            slots_luck = float(bonus.get("slots_luck", 0.0))
            flip_luck = float(bonus.get("flip_luck", 0.0))
            pfc_luck = float(bonus.get("pfc_luck", 0.0))
            req_net = int(r.get("req_net", 0))
            req_games = int(r.get("req_games", 0))

            luck_parts = []
            if slots_luck > 0:
                luck_parts.append(f"Slots +{slots_luck * 100:.1f}%")
            if flip_luck > 0:
                luck_parts.append(f"Flip +{flip_luck * 100:.1f}%")
            if pfc_luck > 0:
                luck_parts.append(f"PFC +{pfc_luck * 100:.1f}%")
            luck_txt = " · ".join(luck_parts) if luck_parts else "—"

            blocks.append(
                f"`{i}` {emoji} | **{name}**\n"
                f"{desc}\n"
                f"Req: net ≥ **{req_net:,}** · parties ≥ **{req_games:,}**\n"
                f"Bonus: -{cd}s CD · +{win_pct}% net · {luck_txt}"
            )

        emb.description = "\n\n".join(blocks)
        emb.set_footer(text="Astuce : `+casinoranks panel` pour un panel plus joli dans le salon rank.")
        await ctx.send(embed=emb)

    @commands.command(name="trade")
    async def trade(self, ctx, role: discord.Role, *, message: str):
        """Annonce un trade de rôles : tu proposes @Rôle + message. Un seul partenaire peut répondre."""
        cfg = await get_casino_config(ctx.guild.id)
        err = await _must_be_channel(ctx, cfg, "channel_trade")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        if role.is_default() or role.managed:
            return await ctx.send(embed=error_embed("Trade", "Rôle invalide (managed ou @everyone)."))
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Trade", "Le bot ne peut pas gérer ce rôle."))
        if role not in ctx.author.roles:
            return await ctx.send(embed=error_embed("Trade", "Tu dois **posséder** ce rôle pour le proposer."))
        if not message.strip():
            return await ctx.send(embed=error_embed("Trade", "Ajoute un message (ex. ce que tu proposes en échange)."))
        tid = str(uuid.uuid4())[:10]
        col = get_collection("role_trades")
        if col is None:
            return await ctx.send(embed=error_embed("DB", "Erreur collection."))
        color = await get_guild_color(ctx.guild.id)
        emb = discord.Embed(
            title="🤝 Trade de rôles",
            description=f"**Auteur :** {ctx.author.mention}\n"
            f"**Je propose le rôle :** {role.mention}\n\n**Message :**\n{message[:1800]}",
            color=color,
        )
        emb.set_footer(text=f"ID trade: {tid} · +tradecancel {tid} (auteur)")
        view = TradeOpenView(tid)
        msg = await ctx.send(embed=emb, view=view)
        self.bot.add_view(view)
        await col.insert_one({
            "_id": tid,
            "guild_id": str(ctx.guild.id),
            "channel_id": str(ctx.channel.id),
            "message_id": str(msg.id),
            "author_id": str(ctx.author.id),
            "wanted_role_id": str(role.id),  # rôle proposé par l'auteur (clé conservée pour compat DB)
            "message": message[:2000],
            "status": "open",
            "claimer_id": None,
            "thread_id": None,
            "author_role_id": None,
            "claimer_role_id": None,
            "author_conf": False,
            "claimer_conf": False,
            "final_panel_sent": False,
        })

    @commands.command(name="tradecancel")
    async def tradecancel(self, ctx, trade_id: str):
        """Annule ton trade ouvert (auteur uniquement)."""
        col = get_collection("role_trades")
        if col is None:
            return await ctx.send(embed=error_embed("DB", "Erreur."))
        doc = await col.find_one({"_id": trade_id, "guild_id": str(ctx.guild.id)})
        if not doc:
            return await ctx.send(embed=error_embed("Trade", "ID introuvable."))
        if str(ctx.author.id) != doc["author_id"] and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=error_embed("Trade", "Seul l’auteur peut annuler."))
        if doc["status"] not in ("open", "claimed", "locking"):
            return await ctx.send(embed=error_embed("Trade", "Ce trade est déjà terminé ou verrouillé."))
        await col.update_one({"_id": trade_id}, {"$set": {"status": "cancelled"}})
        tid_th = doc.get("thread_id")
        if tid_th:
            t = ctx.guild.get_thread(int(tid_th))
            if t:
                try:
                    await t.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass
        ch = ctx.guild.get_channel(int(doc["channel_id"]))
        if ch:
            try:
                m = await ch.fetch_message(int(doc["message_id"]))
                await m.edit(view=None)
                await m.reply("❌ Trade annulé.", mention_author=False)
            except Exception:
                pass
        await ctx.send(embed=success_embed("Trade", "Trade annulé.", await get_guild_color(ctx.guild.id)))

    @commands.command(name="auctionbuyout")
    async def auction_buyout_cmd(self, ctx, auction_id: str, member: discord.Member):
        """(Vendeur) Vend immédiatement au prix d’achat immédiat à @membre — seul le vendeur lance la vente."""
        cfg = await get_casino_config(ctx.guild.id)
        ach = cfg.get("auction_channel_id")
        if ach and ctx.channel.id != ach:
            ch = ctx.guild.get_channel(ach)
            if ch:
                return await ctx.send(embed=error_embed("Enchères", f"Utilise {ch.mention}."))
        col = get_collection("role_auctions")
        doc = await col.find_one({"_id": auction_id, "guild_id": str(ctx.guild.id), "status": "active"})
        if not doc:
            return await ctx.send(embed=error_embed("Enchères", "Enchère introuvable ou terminée."))
        if str(ctx.author.id) != doc["seller_id"] and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=error_embed("Enchères", "Seul le **vendeur** peut valider un achat immédiat."))
        bo = doc.get("buyout")
        if not bo:
            return await ctx.send(embed=error_embed("Enchères", "Pas de prix d’achat immédiat sur cette vente."))
        if member.bot or member.id == int(doc["seller_id"]):
            return await ctx.send(embed=error_embed("Enchères", "Acheteur invalide."))
        role = ctx.guild.get_role(int(doc["role_id"]))
        seller = ctx.guild.get_member(int(doc["seller_id"]))
        if not role or not seller:
            return await ctx.send(embed=error_embed("Enchères", "Rôle ou vendeur introuvable."))
        if role not in seller.roles:
            return await ctx.send(embed=error_embed("Enchères", "Le vendeur n’a plus le rôle."))
        bal = await get_balance(ctx.guild.id, member.id)
        if bal < int(bo):
            return await ctx.send(embed=error_embed("Enchères", f"{member.mention} n’a pas **{bo}** SayuCoins."))
        prev = doc.get("current_bidder_id")
        prev_amt = int(doc["current_bid"])
        if prev:
            await add_coins(ctx.guild.id, int(prev), prev_amt)
        if not await remove_coins(ctx.guild.id, member.id, int(bo)):
            return await ctx.send(embed=error_embed("Enchères", "Paiement impossible."))
        await add_coins(ctx.guild.id, seller.id, int(bo))
        try:
            await seller.remove_roles(role, reason="Enchère achat immédiat (vendeur)")
            await member.add_roles(role, reason="Enchère achat immédiat")
        except discord.HTTPException as e:
            await add_coins(ctx.guild.id, member.id, int(bo))
            await remove_coins(ctx.guild.id, seller.id, int(bo))
            if prev:
                await remove_coins(ctx.guild.id, int(prev), prev_amt)
            return await ctx.send(embed=error_embed("Enchères", f"Erreur rôles : {e}"))
        await col.update_one({"_id": auction_id}, {"$set": {"status": "sold_buyout", "buyout_buyer_id": str(member.id)}})
        await ctx.send(
            embed=success_embed(
                "Enchères",
                f"Achat immédiat : {member.mention} a reçu {role.mention} pour **{bo}** SayuCoins.",
                await get_guild_color(ctx.guild.id),
            )
        )

    async def _trade_try_final_panel(self, guild: discord.Guild, trade_id: str):
        col = get_collection("role_trades")
        if col is None:
            return
        doc = await col.find_one({"_id": trade_id})
        if not doc or doc.get("status") != "claimed" or doc.get("final_panel_sent"):
            return
        if not doc.get("author_role_id") or not doc.get("claimer_role_id"):
            return
        thread = guild.get_thread(int(doc["thread_id"])) if doc.get("thread_id") else None
        if not thread:
            return
        author = guild.get_member(int(doc["author_id"]))
        claimer = guild.get_member(int(doc["claimer_id"]))
        ar = guild.get_role(int(doc["author_role_id"]))
        cr = guild.get_role(int(doc["claimer_role_id"]))
        if not all([author, claimer, ar, cr]):
            return
        color = await get_guild_color(guild.id)
        emb = discord.Embed(
            title="🔒 Validation finale",
            description=f"**{author.display_name}** donne : {ar.mention}\n"
            f"**{claimer.display_name}** donne : {cr.mention}\n\n"
            f"Les **deux** doivent cliquer sur **Confirmer** pour appliquer l’échange.",
            color=color,
        )
        fv = TradeFinalView(trade_id)
        self.bot.add_view(fv)
        await thread.send(embed=emb, view=fv)
        await col.update_one({"_id": trade_id}, {"$set": {"final_panel_sent": True}})

    async def _trade_do_swap_body(
        self,
        guild: discord.Guild,
        trade_id: str,
        panel_message: discord.Message,
    ):
        col = get_collection("role_trades")
        if col is None:
            return
        doc = await col.find_one({"_id": trade_id})
        if not doc:
            return
        author = guild.get_member(int(doc["author_id"]))
        claimer = guild.get_member(int(doc["claimer_id"]))
        ar = guild.get_role(int(doc["author_role_id"]))
        cr = guild.get_role(int(doc["claimer_role_id"]))
        thread = panel_message.channel
        if not all([author, claimer, ar, cr]):
            await col.update_one(
                {"_id": trade_id},
                {"$set": {"status": "claimed", "author_conf": False, "claimer_conf": False}},
            )
            await thread.send("Membre ou rôle introuvable — échange annulé. Réessaie ou `+tradecancel`.")
            return
        if ar not in author.roles or cr not in claimer.roles:
            await col.update_one(
                {"_id": trade_id},
                {"$set": {"status": "claimed", "author_conf": False, "claimer_conf": False}},
            )
            await thread.send("Un des rôles n’est plus sur le bon membre — réessaie après correction ou annule.")
            return
        try:
            await author.remove_roles(ar, reason="Trade rôles")
            await claimer.add_roles(ar, reason="Trade rôles")
            await claimer.remove_roles(cr, reason="Trade rôles")
            await author.add_roles(cr, reason="Trade rôles")
        except discord.HTTPException as e:
            await col.update_one(
                {"_id": trade_id},
                {"$set": {"status": "claimed", "author_conf": False, "claimer_conf": False}},
            )
            await thread.send(f"Erreur Discord (hiérarchie / permissions) : {e}")
            return
        await col.update_one({"_id": trade_id}, {"$set": {"status": "done"}})
        try:
            await panel_message.edit(view=None)
        except discord.HTTPException:
            pass
        await thread.send(
            f"✅ **Échange terminé** : {author.mention} a reçu {cr.mention}, {claimer.mention} a reçu {ar.mention}."
        )

    async def _handle_rtclaim(self, interaction: discord.Interaction, trade_id: str):
        if not interaction.guild:
            await interaction.response.send_message("Hors serveur.", ephemeral=True)
            return
        col = get_collection("role_trades")
        if col is None:
            await interaction.response.send_message("Base indisponible.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        doc = await col.find_one({"_id": trade_id, "guild_id": str(interaction.guild.id)})
        if not doc or doc["status"] != "open":
            await interaction.followup.send("Trade fermé ou déjà pris.", ephemeral=True)
            return
        if str(interaction.user.id) == doc["author_id"]:
            await interaction.followup.send("Tu ne peux pas répondre à ton propre trade.", ephemeral=True)
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not member:
            await interaction.followup.send("Membre introuvable.", ephemeral=True)
            return
        result = await col.update_one(
            {"_id": trade_id, "guild_id": str(interaction.guild.id), "status": "open"},
            {"$set": {"claimer_id": str(interaction.user.id), "status": "claimed"}},
        )
        if result.matched_count == 0:
            await interaction.followup.send("Quelqu’un d’autre a déjà pris ce trade.", ephemeral=True)
            return
        doc = await col.find_one({"_id": trade_id})
        bot_me = interaction.guild.me
        author = interaction.guild.get_member(int(doc["author_id"]))
        ch = interaction.guild.get_channel(int(doc["channel_id"]))
        if not author:
            await col.update_one({"_id": trade_id}, {"$set": {"status": "open", "claimer_id": None}})
            await interaction.followup.send("Auteur introuvable — trade réouvert.", ephemeral=True)
            return
        if ch and isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(int(doc["message_id"]))
                await msg.edit(view=None)
                await msg.reply(
                    f"✅ **{member.display_name}** a pris ce trade — la suite se passe dans le fil privé.",
                    mention_author=False,
                )
            except discord.HTTPException:
                pass
        if not isinstance(ch, discord.TextChannel):
            await col.update_one({"_id": trade_id}, {"$set": {"status": "open", "claimer_id": None}})
            await interaction.followup.send("Salon d’annonce invalide — trade réouvert.", ephemeral=True)
            return
        try:
            thread = await _create_private_thread(ch, f"Trade-{trade_id}")
            await _thread_add_user_safe(thread, author)
            await _thread_add_user_safe(thread, member)
            await col.update_one({"_id": trade_id}, {"$set": {"thread_id": str(thread.id)}})
        except (TypeError, discord.HTTPException) as e:
            await col.update_one({"_id": trade_id}, {"$set": {"status": "open", "claimer_id": None}})
            await interaction.followup.send(f"Impossible de créer le fil privé : {e}", ephemeral=True)
            if ch and isinstance(ch, discord.TextChannel):
                try:
                    msg = await ch.fetch_message(int(doc["message_id"]))
                    ov = TradeOpenView(trade_id)
                    self.bot.add_view(ov)
                    await msg.edit(view=ov)
                except discord.HTTPException:
                    pass
            return
        offered = interaction.guild.get_role(int(doc["wanted_role_id"]))  # rôle proposé par l'auteur
        if not offered:
            await col.update_one({"_id": trade_id}, {"$set": {"status": "open", "claimer_id": None}})
            await interaction.followup.send("Rôle proposé introuvable — trade réouvert.", ephemeral=True)
            return
        if offered not in author.roles:
            await col.update_one({"_id": trade_id}, {"$set": {"status": "open", "claimer_id": None}})
            await interaction.followup.send("L’auteur n’a plus le rôle proposé — trade réouvert.", ephemeral=True)
            return
        if offered >= interaction.guild.me.top_role or offered.managed or offered.is_default():
            await col.update_one({"_id": trade_id}, {"$set": {"status": "open", "claimer_id": None}})
            await interaction.followup.send("Le bot ne peut plus gérer ce rôle — trade réouvert.", ephemeral=True)
            return

        aroles = _tradable_roles(author, bot_me)
        croles = _tradable_roles(member, bot_me)
        color = await get_guild_color(interaction.guild.id)
        emb = discord.Embed(
            title="🤝 Trade — négociation",
            description=f"**Auteur :** {author.mention}\n**Partenaire :** {member.mention}\n\n"
            f"**Rôle proposé (auteur) :** {offered.mention}\n\n"
            f"**Rôles échangeables (partenaire) :**\n{(', '.join(r.mention for r in croles) or '*(aucun)*')}\n\n"
            f"**Rôles échangeables (auteur) :**\n{(', '.join(r.mention for r in aroles) or '*(aucun)*')}",
            color=color,
        )
        emb.add_field(
            name="Étapes",
            value="1. **Partenaire** : menu déroulant — rôle que tu donnes.\n"
            "2. **Auteur** : bouton **je confirme céder le rôle proposé**.\n"
            "3. Double confirmation pour appliquer l’échange.",
            inline=False,
        )
        if not croles:
            await thread.send(
                embed=emb,
                content="⚠️ Le partenaire n’a aucun rôle échangeable — annule ou change de partenaire.",
            )
            await interaction.followup.send(f"Fil créé : {thread.mention} (bloqué : partenaire sans rôle à offrir).", ephemeral=True)
            return
        opts = [SelectOption(label=r.name[:100], value=str(r.id)) for r in croles[:25]]
        nv = build_trade_negotiation_view(trade_id, opts)
        self.bot.add_view(nv)
        await thread.send(embed=emb, view=nv)
        await interaction.followup.send(f"✅ Trade réservé — fil privé : {thread.mention}", ephemeral=True)

    async def _handle_rtsela(self, interaction: discord.Interaction, trade_id: str):
        if not interaction.guild:
            return
        col = get_collection("role_trades")
        if col is None:
            await interaction.response.send_message("Base indisponible.", ephemeral=True)
            return
        doc = await col.find_one({"_id": trade_id, "guild_id": str(interaction.guild.id)})
        if not doc or doc.get("status") != "claimed":
            await interaction.response.send_message("Trade invalide.", ephemeral=True)
            return
        if doc.get("final_panel_sent"):
            await interaction.response.send_message(
                "Le panneau final est déjà là — annule avec `+tradecancel` si besoin.",
                ephemeral=True,
            )
            return
        if str(interaction.user.id) != doc.get("claimer_id"):
            await interaction.response.send_message("Seul le partenaire utilise ce menu.", ephemeral=True)
            return
        vals = interaction.data.get("values") or []
        if not vals:
            await interaction.response.send_message("Choix vide.", ephemeral=True)
            return
        rid = int(vals[0])
        role = interaction.guild.get_role(rid)
        claimer = interaction.guild.get_member(int(doc["claimer_id"]))
        if not role or not claimer or role not in claimer.roles or role.managed or role.is_default():
            await interaction.response.send_message("Rôle invalide.", ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("Le bot ne peut pas transférer ce rôle.", ephemeral=True)
            return
        await col.update_one({"_id": trade_id}, {"$set": {"claimer_role_id": str(rid)}})
        await interaction.response.send_message(f"✅ Tu offres : {role.mention}.", ephemeral=True)
        await self._trade_try_final_panel(interaction.guild, trade_id)

    async def _handle_rtgivew(self, interaction: discord.Interaction, trade_id: str):
        if not interaction.guild:
            return
        col = get_collection("role_trades")
        if col is None:
            await interaction.response.send_message("Base indisponible.", ephemeral=True)
            return
        doc = await col.find_one({"_id": trade_id, "guild_id": str(interaction.guild.id)})
        if not doc or doc.get("status") != "claimed":
            await interaction.response.send_message("Trade invalide.", ephemeral=True)
            return
        if doc.get("final_panel_sent"):
            await interaction.response.send_message(
                "Le panneau final est déjà là — annule avec `+tradecancel` si besoin.",
                ephemeral=True,
            )
            return
        if str(interaction.user.id) != doc.get("author_id"):
            await interaction.response.send_message("Seul l’auteur utilise ce bouton.", ephemeral=True)
            return
        offered = interaction.guild.get_role(int(doc["wanted_role_id"]))
        author = interaction.guild.get_member(int(doc["author_id"]))
        if not offered or not author or offered not in author.roles:
            await interaction.response.send_message("Tu n’as plus le rôle proposé.", ephemeral=True)
            return
        if offered >= interaction.guild.me.top_role:
            await interaction.response.send_message("Le bot ne peut pas transférer ce rôle.", ephemeral=True)
            return
        await col.update_one({"_id": trade_id}, {"$set": {"author_role_id": str(offered.id)}})
        await interaction.response.send_message(f"✅ Tu confirmes céder {offered.mention}.", ephemeral=True)
        await self._trade_try_final_panel(interaction.guild, trade_id)

    async def _handle_rtconf(self, interaction: discord.Interaction, trade_id: str, side: str):
        if not interaction.guild:
            return
        col = get_collection("role_trades")
        if col is None:
            await interaction.response.send_message("Base indisponible.", ephemeral=True)
            return
        doc = await col.find_one({"_id": trade_id, "guild_id": str(interaction.guild.id)})
        if not doc:
            await interaction.response.send_message("Trade introuvable.", ephemeral=True)
            return
        st = doc.get("status")
        if st == "done":
            await interaction.response.send_message("Ce trade est déjà terminé.", ephemeral=True)
            return
        if st == "locking":
            await interaction.response.send_message("Échange en cours…", ephemeral=True)
            return
        if st != "claimed" or not doc.get("final_panel_sent"):
            await interaction.response.send_message("Étape invalide ou panneau manquant.", ephemeral=True)
            return
        if side == "author":
            if str(interaction.user.id) != doc["author_id"]:
                await interaction.response.send_message("Ce bouton est pour l’auteur du trade.", ephemeral=True)
                return
            await col.update_one({"_id": trade_id}, {"$set": {"author_conf": True}})
        else:
            if str(interaction.user.id) != doc.get("claimer_id"):
                await interaction.response.send_message("Ce bouton est pour le partenaire.", ephemeral=True)
                return
            await col.update_one({"_id": trade_id}, {"$set": {"claimer_conf": True}})
        doc2 = await col.find_one({"_id": trade_id})
        if doc2.get("author_conf") and doc2.get("claimer_conf"):
            lock = await col.update_one(
                {"_id": trade_id, "status": "claimed"},
                {"$set": {"status": "locking"}},
            )
            if lock.modified_count:
                await interaction.response.defer(ephemeral=True)
                await self._trade_do_swap_body(interaction.guild, trade_id, interaction.message)
                await interaction.followup.send("✅ Échange appliqué (voir le fil).", ephemeral=True)
                return
            doc3 = await col.find_one({"_id": trade_id})
            if doc3 and doc3.get("status") == "done":
                await interaction.response.send_message("✅ Échange déjà effectué.", ephemeral=True)
                return
        await interaction.response.send_message("✅ Confirmation enregistrée.", ephemeral=True)

    async def _handle_auc_accept(self, interaction: discord.Interaction, auction_id: str):
        if not interaction.guild:
            return
        col = get_collection("role_auctions")
        if col is None:
            await interaction.response.send_message("Base indisponible.", ephemeral=True)
            return
        doc = await col.find_one({"_id": auction_id, "guild_id": str(interaction.guild.id), "status": "active"})
        if not doc:
            await interaction.response.send_message("Enchère terminée ou introuvable.", ephemeral=True)
            return
        if str(interaction.user.id) != doc["seller_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Seul le **vendeur** peut accepter une offre.", ephemeral=True)
            return
        buyer_id = doc.get("current_bidder_id")
        if not buyer_id:
            await interaction.response.send_message("Aucune offre pour le moment.", ephemeral=True)
            return
        role = interaction.guild.get_role(int(doc["role_id"]))
        seller = interaction.guild.get_member(int(doc["seller_id"]))
        buyer = interaction.guild.get_member(int(buyer_id))
        if not role or not seller or not buyer:
            await interaction.response.send_message("Rôle / vendeur / acheteur introuvable.", ephemeral=True)
            return
        if role not in seller.roles:
            await interaction.response.send_message("Tu n’as plus le rôle à vendre.", ephemeral=True)
            return

        price = int(doc.get("current_bid", 0))
        if price < 1:
            await interaction.response.send_message("Montant invalide.", ephemeral=True)
            return

        lock = await col.update_one(
            {"_id": auction_id, "guild_id": str(interaction.guild.id), "status": "active"},
            {"$set": {"status": "selling"}},
        )
        if not lock.modified_count:
            await interaction.response.send_message("Vente déjà en cours.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await add_coins(interaction.guild.id, seller.id, price)
        try:
            await seller.remove_roles(role, reason="Enchère: offre acceptée")
            await buyer.add_roles(role, reason="Enchère: offre acceptée")
        except discord.HTTPException as e:
            await remove_coins(interaction.guild.id, seller.id, price)
            await col.update_one({"_id": auction_id}, {"$set": {"status": "active"}})
            await interaction.followup.send(f"Erreur Discord (rôles) : {e}", ephemeral=True)
            return

        await col.update_one(
            {"_id": auction_id},
            {"$set": {"status": "sold_accept", "accepted_at": datetime.now(timezone.utc)}},
        )
        try:
            await interaction.message.edit(view=None)
        except discord.HTTPException:
            pass
        try:
            thread_id = doc.get("thread_id")
            if thread_id:
                th = interaction.guild.get_thread(int(thread_id))
                if th:
                    await th.send(
                        f"✅ Offre acceptée : {buyer.mention} a reçu {role.mention} pour **{price}** SayuCoins."
                    )
                    try:
                        await th.edit(archived=True, locked=True)
                    except discord.HTTPException:
                        pass
        except Exception:
            pass
        await interaction.followup.send("✅ Offre acceptée (voir le fil).", ephemeral=True)

    async def _handle_game_modal_submit(self, interaction: discord.Interaction, game: str, bet_raw: str, choice_raw: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Hors serveur.", ephemeral=True)
        game = (game or "").lower().strip()
        if game not in ("slots", "flip", "pfc", "blackjack"):
            return await interaction.response.send_message("Jeu invalide.", ephemeral=True)
        try:
            bet = int(str(bet_raw).replace(" ", "").replace(",", ""))
        except ValueError:
            return await interaction.response.send_message("Mise invalide.", ephemeral=True)
        cfg = await get_casino_config(interaction.guild.id)
        # validate_bet attend un ctx classique; on refait les checks essentiels ici
        if not cfg.get("enabled", True):
            return await interaction.response.send_message("Casino désactivé.", ephemeral=True)
        if bet < int(cfg["min_bet"]) or bet > int(cfg["max_bet"]):
            return await interaction.response.send_message(
                f"Mise autorisée: **{cfg['min_bet']}–{cfg['max_bet']}**", ephemeral=True
            )
        bal = await get_balance(interaction.guild.id, interaction.user.id)
        if bal < bet:
            return await interaction.response.send_message("Solde insuffisant.", ephemeral=True)
        # Cooldown (avec bonus rank)
        bonus = await get_member_casino_rank_bonus(interaction.guild, interaction.user)
        eff_cd = max(1, int(cfg["cooldown_seconds"]) - int(bonus.get("cooldown_minus", 0)))
        ok_cd, left = await check_casino_cooldown(interaction.guild.id, interaction.user.id, game, eff_cd)
        if not ok_cd:
            return await interaction.response.send_message(f"Cooldown : **{left}s**", ephemeral=True)
        used = await get_daily_count(interaction.guild.id, interaction.user.id)
        if used >= int(cfg["daily_game_limit"]):
            return await interaction.response.send_message("Limite journalière atteinte.", ephemeral=True)

        parent = interaction.channel
        if not isinstance(parent, discord.TextChannel):
            return await interaction.response.send_message("Utilise un salon texte.", ephemeral=True)
        try:
            thread = await _create_private_thread(parent, f"{game}-{interaction.user.display_name}")
            await _thread_add_user_safe(thread, interaction.user)
        except Exception:
            return await interaction.response.send_message("Impossible de créer le fil privé.", ephemeral=True)

        # Enregistrer la partie en "pending" : on lance via bouton dans le fil (plus visible + moins boring)
        gid = interaction.guild.id
        game_id = str(uuid.uuid4())[:10]
        pend = get_collection("casino_pending_games")
        if pend is None:
            return await interaction.response.send_message("DB indisponible.", ephemeral=True)
        await pend.insert_one({
            "_id": game_id,
            "guild_id": str(gid),
            "user_id": str(interaction.user.id),
            "game": game,
            "bet": int(bet),
            "choice": (choice_raw or "").strip(),
            "thread_id": str(thread.id),
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
        })

        color = await get_guild_color(gid)
        emb = discord.Embed(
            title="🎮 Partie prête",
            description=f"Jeu: **{game}**\nMise: **{bet}**\n"
            f"{('Choix: **' + (choice_raw or '').strip() + '**\\n') if (choice_raw or '').strip() else ''}"
            "Clique sur **Lancer la partie** pour démarrer avec une petite animation.",
            color=color,
        )
        v = CasinoGameStartView(game_id)
        self.bot.add_view(v)
        await thread.send(embed=emb, view=v)

        # Message visible dans le salon + bouton lien (évite le côté "fil disparu")
        link_view = View(timeout=None)
        link_view.add_item(Button(label="Ouvrir le fil", style=discord.ButtonStyle.link, url=thread.jump_url))
        await interaction.response.send_message(
            f"{interaction.user.mention} ta partie est prête : {thread.mention}",
            view=link_view,
        )

    async def _handle_cgplay(self, interaction: discord.Interaction, game_id: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        pend = get_collection("casino_pending_games")
        if pend is None:
            return await interaction.response.send_message("DB indisponible.", ephemeral=True)
        doc = await pend.find_one({"_id": game_id, "guild_id": str(interaction.guild.id)})
        if not doc or doc.get("status") != "pending":
            return await interaction.response.send_message("Partie introuvable ou déjà lancée.", ephemeral=True)
        if str(interaction.user.id) != doc.get("user_id"):
            return await interaction.response.send_message("Ce n’est pas ta partie.", ephemeral=True)

        game = (doc.get("game") or "").lower()
        bet = int(doc.get("bet") or 0)
        choice = (doc.get("choice") or "").lower().strip()
        cfg = await get_casino_config(interaction.guild.id)

        # Lock
        lock = await pend.update_one({"_id": game_id, "status": "pending"}, {"$set": {"status": "running"}})
        if not lock.modified_count:
            return await interaction.response.send_message("Partie déjà en cours.", ephemeral=True)

        # Paiement + quota
        if bet < 1 or not await remove_coins(interaction.guild.id, interaction.user.id, bet):
            await pend.update_one({"_id": game_id}, {"$set": {"status": "pending"}})
            return await interaction.response.send_message("Paiement impossible.", ephemeral=True)
        await inc_daily_count(interaction.guild.id, interaction.user.id)

        bonus = await get_member_casino_rank_bonus(interaction.guild, interaction.user)
        currency = (await get_guild_config(interaction.guild.id) or {}).get("currency_emoji", "💰")
        color = await get_guild_color(interaction.guild.id)

        # Animation message (on réutilise le message actuel)
        try:
            await interaction.response.defer()
        except Exception:
            pass
        msg = interaction.message

        async def anim(texts: list[str], delay: float = 0.7):
            for t in texts:
                try:
                    await msg.edit(embed=discord.Embed(title="⏳ Partie en cours…", description=t, color=color), view=None)
                except Exception:
                    pass
                await asyncio.sleep(delay)

        net = 0
        title = ""
        desc = ""

        if game == "slots":
            await anim(["🎰 Les rouleaux tournent…", "🍒 🍋 🍊 …", "💎 7️⃣ … presque !"], delay=0.6)
            luck = max(0.0, float(bonus.get("slots_luck", 0.0)))
            symbols = ["🍒", "🍋", "🍊", "💎", "7️⃣"]
            w = [1.0, 1.0, 1.0, 0.6 + (luck * 6.0), 0.35 + (luck * 6.0)]
            a, b, c = random.choices(symbols, weights=w, k=3)
            mult = 0
            if a == b == c:
                mult = 10 if a == "7️⃣" else 8
            elif a == b or b == c or a == c:
                mult = 2
            gross = bet * mult if mult else 0
            net = await take_house_fee(gross, cfg["house_fee_percent"])
            net = apply_rank_win_bonus(net, int(bonus.get("win_bonus_pct", 0)))
            if net:
                await add_coins(interaction.guild.id, interaction.user.id, net)
            await inc_casino_stat(interaction.guild.id, interaction.user.id, wagered=bet, won=net)
            title = "🎰 Slots"
            desc = f"| {a} | {b} | {c} |\n\n" + ("🎉 JACKPOT !" if mult >= 8 else "✅ Gain !" if mult else "😢 Perdu")
        elif game == "flip":
            if choice not in ("pile", "face"):
                await add_coins(interaction.guild.id, interaction.user.id, bet)
                await pend.update_one({"_id": game_id}, {"$set": {"status": "failed"}})
                return await interaction.followup.send("Choix invalide (pile/face).", ephemeral=True)
            await anim([f"🪙 Lancement… (tu as choisi **{choice}**)", "🌀 La pièce tourne…", "…"], delay=0.7)
            luck = max(0.0, float(bonus.get("flip_luck", 0.0)))
            if luck and random.random() < luck:
                result = choice
            else:
                result = random.choice(["pile", "face"])
            win = (choice == result)
            gross = bet * 2 if win else 0
            net = await take_house_fee(gross, cfg["house_fee_percent"]) if win else 0
            net = apply_rank_win_bonus(net, int(bonus.get("win_bonus_pct", 0))) if win else 0
            if net:
                await add_coins(interaction.guild.id, interaction.user.id, net)
            await inc_casino_stat(interaction.guild.id, interaction.user.id, wagered=bet, won=net)
            title = "🪙 Pile ou face"
            desc = f"Choix: **{choice}**\nRésultat: **{result}**\n" + ("✅ Gagné" if win else "❌ Perdu")
        elif game == "pfc":
            PFC = {"pierre": "🪨", "feuille": "📄", "ciseaux": "✂️"}
            if choice not in PFC:
                await add_coins(interaction.guild.id, interaction.user.id, bet)
                await pend.update_one({"_id": game_id}, {"$set": {"status": "failed"}})
                return await interaction.followup.send("Choix invalide (pierre/feuille/ciseaux).", ephemeral=True)
            await anim(["🤖 Le bot réfléchit…", "👀 …", "✋ Choix final !"], delay=0.65)
            luck = max(0.0, float(bonus.get("pfc_luck", 0.0)))
            wins = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}
            if luck and random.random() < luck:
                bot_c = wins[choice]
            else:
                bot_c = random.choice(list(PFC.keys()))
            if choice == bot_c:
                await add_coins(interaction.guild.id, interaction.user.id, bet)
                await inc_casino_stat(interaction.guild.id, interaction.user.id, wagered=bet, won=bet)
                title = "✂️ PFC"
                desc = f"Toi: {PFC[choice]}  vs  Bot: {PFC[bot_c]}\n🤝 Égalité — mise rendue"
                net = 0
            elif wins[choice] == bot_c:
                gross = bet * 2
                net = await take_house_fee(gross, cfg["house_fee_percent"])
                net = apply_rank_win_bonus(net, int(bonus.get("win_bonus_pct", 0)))
                await add_coins(interaction.guild.id, interaction.user.id, net)
                await inc_casino_stat(interaction.guild.id, interaction.user.id, wagered=bet, won=net)
                title = "✂️ PFC"
                desc = f"Toi: {PFC[choice]}  vs  Bot: {PFC[bot_c]}\n✅ Victoire"
            else:
                await inc_casino_stat(interaction.guild.id, interaction.user.id, wagered=bet, won=0)
                title = "✂️ PFC"
                desc = f"Toi: {PFC[choice]}  vs  Bot: {PFC[bot_c]}\n❌ Défaite"
                net = 0
        elif game == "blackjack":
            # Version embed: on démarre une partie blackjack dans le fil (boutons tirer/rester)
            deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 11] * 4
            random.shuffle(deck)
            player = [deck.pop(), deck.pop()]
            dealer = [deck.pop(), deck.pop()]

            def hand_value(cards):
                total = sum(cards)
                aces = cards.count(11)
                while total > 21 and aces:
                    total -= 10
                    aces -= 1
                return total

            class BJ(View):
                def __init__(self):
                    super().__init__(timeout=60)
                    self.player = player
                    self.dealer = dealer
                    self.deck = deck

                async def _finish(self, interaction2: discord.Interaction, net2: int, text: str, clr2: int):
                    await inc_casino_stat(interaction2.guild.id, interaction2.user.id, wagered=bet, won=net2)
                    cog = interaction2.client.get_cog("CasinoCog")
                    if cog and isinstance(interaction2.user, discord.Member):
                        await cog._ranks_autosync_member(interaction2.user)
                        try:
                            await _update_last_games_message(
                                interaction2.guild,
                                f"<t:{int(datetime.now(timezone.utc).timestamp())}:t> 🃏 {interaction2.user.mention} mise **{bet}** → net **{net2}**",
                            )
                        except Exception:
                            pass
                    for c in self.children:
                        c.disabled = True
                    await interaction2.response.edit_message(embed=discord.Embed(title="🃏 Blackjack", description=text, color=clr2), view=self)

                @discord.ui.button(label="Tirer", style=discord.ButtonStyle.primary)
                async def hit(self, interaction2: discord.Interaction, btn: Button):
                    if interaction2.user.id != interaction.user.id:
                        return await interaction2.response.send_message("Pas ta partie.", ephemeral=True)
                    self.player.append(self.deck.pop())
                    pv = hand_value(self.player)
                    if pv > 21:
                        return await self._finish(interaction2, 0, f"Bust. Main: {self.player} ({pv})", 0xED4245)
                    await interaction2.response.edit_message(
                        embed=discord.Embed(
                            title="🃏 Blackjack",
                            description=f"Toi: {self.player} ({pv})\nBot: {self.dealer[0]} ?",
                            color=color,
                        ),
                        view=self,
                    )

                @discord.ui.button(label="Rester", style=discord.ButtonStyle.secondary)
                async def stay(self, interaction2: discord.Interaction, btn: Button):
                    if interaction2.user.id != interaction.user.id:
                        return await interaction2.response.send_message("Pas ta partie.", ephemeral=True)
                    while hand_value(self.dealer) < 17:
                        self.dealer.append(self.deck.pop())
                    pv, dv = hand_value(self.player), hand_value(self.dealer)
                    net2 = 0
                    if dv > 21 or pv > dv:
                        gross2 = bet * 2
                        net2 = await take_house_fee(gross2, cfg["house_fee_percent"])
                        net2 = apply_rank_win_bonus(net2, int(bonus.get("win_bonus_pct", 0)))
                        await add_coins(interaction2.guild.id, interaction2.user.id, net2)
                        txt = "✅ Victoire"
                        clr2 = 0x57F287
                    elif pv == dv:
                        await add_coins(interaction2.guild.id, interaction2.user.id, bet)
                        net2 = bet
                        txt = "🤝 Égalité"
                        clr2 = 0x5865F2
                    else:
                        txt = "❌ Défaite"
                        clr2 = 0xED4245
                    return await self._finish(
                        interaction2,
                        net2,
                        f"Toi: {self.player} ({pv})\nBot: {self.dealer} ({dv})\n{txt} — Net **{net2}** {currency}",
                        clr2,
                    )

            title = "🃏 Blackjack"
            desc = f"Mise **{bet}**\nToi: {player} ({hand_value(player)})\nBot: {dealer[0]} ?\n\nClique Tirer/Rester."
            # Le rendu final est un message avec boutons
            await pend.update_one({"_id": game_id}, {"$set": {"status": "done", "ended_at": datetime.now(timezone.utc)}})
            try:
                await msg.edit(embed=discord.Embed(title=title, description=desc, color=color), view=BJ())
            except Exception:
                pass
            await self._ranks_autosync_member(interaction.user)
            return
        else:
            await add_coins(interaction.guild.id, interaction.user.id, bet)
            await pend.update_one({"_id": game_id}, {"$set": {"status": "failed"}})
            return await interaction.followup.send("Jeu non supporté.", ephemeral=True)

        await pend.update_one({"_id": game_id}, {"$set": {"status": "done", "ended_at": datetime.now(timezone.utc)}})
        await self._ranks_autosync_member(interaction.user)
        try:
            await _update_last_games_message(
                interaction.guild,
                f"<t:{int(datetime.now(timezone.utc).timestamp())}:t> {title.split()[0]} {interaction.user.mention} mise **{bet}** → net **{net}**",
            )
        except Exception:
            pass

        final = discord.Embed(title=title, description=f"{desc}\n\nMise **{bet}** → Net **{net}** {currency}", color=color)
        try:
            await msg.edit(embed=final, view=None)
        except Exception:
            pass
        try:
            await interaction.followup.send("✅ Partie terminée.", ephemeral=True)
        except Exception:
            pass

    @commands.command(name="embedslots")
    @commands.has_permissions(administrator=True)
    async def embedslots(self, ctx):
        color = await get_guild_color(ctx.guild.id)
        emb = discord.Embed(
            title="🎰 Slots — Lance une partie",
            description="Clique sur **Lancer une partie**, choisis ta mise, et le bot crée un **fil privé**.",
            color=color,
        )
        v = CasinoGameEntryView("slots")
        self.bot.add_view(v)
        await ctx.send(embed=emb, view=v)

    @commands.command(name="embedflip")
    @commands.has_permissions(administrator=True)
    async def embedflip(self, ctx):
        color = await get_guild_color(ctx.guild.id)
        emb = discord.Embed(
            title="🪙 Pile ou face — Lance une partie",
            description="Clique sur **Lancer une partie**, entre ta mise et ton choix (**pile**/**face**) → fil privé.",
            color=color,
        )
        v = CasinoGameEntryView("flip")
        self.bot.add_view(v)
        await ctx.send(embed=emb, view=v)

    @commands.command(name="embedpfc")
    @commands.has_permissions(administrator=True)
    async def embedpfc(self, ctx):
        color = await get_guild_color(ctx.guild.id)
        emb = discord.Embed(
            title="✂️ PFC — Lance une partie",
            description="Clique sur **Lancer une partie**, mise + choix (**pierre/feuille/ciseaux**) → fil privé.",
            color=color,
        )
        v = CasinoGameEntryView("pfc")
        self.bot.add_view(v)
        await ctx.send(embed=emb, view=v)

    @commands.command(name="embedblackjack", aliases=["embedbj"])
    @commands.has_permissions(administrator=True)
    async def embedblackjack(self, ctx):
        color = await get_guild_color(ctx.guild.id)
        emb = discord.Embed(
            title="🃏 Blackjack — Lance une partie",
            description="Clique sur **Lancer une partie**, choisis ta mise → fil privé + boutons Tirer/Rester.",
            color=color,
        )
        v = CasinoGameEntryView("blackjack")
        self.bot.add_view(v)
        await ctx.send(embed=emb, view=v)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != InteractionType.component:
            return
        cid = interaction.data.get("custom_id") or ""
        if cid.startswith("aucjoin:"):
            if not interaction.guild:
                return
            aid = cid.split(":", 1)[1]
            col = get_collection("role_auctions")
            doc = await col.find_one({"_id": aid, "status": "active"}) if col is not None else None
            if not doc or not doc.get("thread_id"):
                await interaction.response.send_message("Enchère introuvable ou terminée.", ephemeral=True)
                return
            thread = interaction.guild.get_thread(int(doc["thread_id"]))
            if not thread:
                await interaction.response.send_message("Fil d’enchère introuvable (archivé ou supprimé).", ephemeral=True)
                return
            try:
                await thread.add_user(interaction.user)
            except discord.HTTPException:
                await interaction.response.send_message(
                    f"Tu es peut-être déjà dans le fil, ou l’ajout a échoué : {thread.mention}",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"Tu as accès à l’enchère : {thread.mention}",
                ephemeral=True,
            )
            return
        if not cid.startswith("auc:"):
            return
        parts = cid.split(":")
        if len(parts) < 3:
            return
        aid, action = parts[1], parts[2]
        col = get_collection("role_auctions")
        doc = await col.find_one({"_id": aid, "status": "active"})
        if not doc:
            if interaction.response.is_done():
                return
            await interaction.response.send_message("Enchère terminée ou introuvable.", ephemeral=True)
            return
        cfg = await get_casino_config(interaction.guild.id)
        role = interaction.guild.get_role(int(doc["role_id"]))
        if not role:
            await interaction.response.send_message("Rôle introuvable.", ephemeral=True)
            return
        if action == "accept":
            # Callback déjà géré par la View, mais on garde ce fallback.
            await self._handle_auc_accept(interaction, aid)
            return
        try:
            inc = int(action)
        except ValueError:
            await interaction.response.send_message(
                "L’achat immédiat ne se fait **plus** par bouton : le **vendeur** utilise "
                f"`+auctionbuyout {aid} @acheteur` dans le salon enchères.",
                ephemeral=True,
            )
            return
        bid = int(doc["current_bid"]) + max(inc, cfg.get("bid_increment_min", 100))
        prev = doc.get("current_bidder_id")
        prev_amt = int(doc["current_bid"])
        if str(interaction.user.id) == doc["seller_id"]:
            await interaction.response.send_message("Vous ne pouvez pas enchérir sur votre vente.", ephemeral=True)
            return
        bal = await get_balance(interaction.guild.id, interaction.user.id)
        if bal < bid:
            await interaction.response.send_message(f"Il vous faut **{bid}** SayuCoins.", ephemeral=True)
            return
        if prev and prev != str(interaction.user.id):
            await add_coins(interaction.guild.id, int(prev), prev_amt)
        if not await remove_coins(interaction.guild.id, interaction.user.id, bid):
            await interaction.response.send_message("Solde insuffisant.", ephemeral=True)
            return
        await col.update_one({"_id": aid}, {"$set": {"current_bid": bid, "current_bidder_id": str(interaction.user.id)}})
        doc2 = await col.find_one({"_id": aid})
        ea = doc2.get("ends_at")
        ts = int(ea.timestamp()) if hasattr(ea, "timestamp") else 0
        bo = doc2.get("buyout")
        extra = (
            f"Achat immédiat : **{bo}** SC — vendeur : `+auctionbuyout {aid} @acheteur`\n" if bo else ""
        )
        emb = discord.Embed(
            title=interaction.message.embeds[0].title,
            description=f"Vendeur: <@{doc2['seller_id']}>\n**Enchère actuelle: {doc2['current_bid']}** — <@{interaction.user.id}>\n"
            f"{extra}Fin: <t:{ts}:R>\n`ID: {aid}`",
            color=interaction.message.embeds[0].color,
        )
        await interaction.response.edit_message(embed=emb)
        await interaction.followup.send(f"✅ Enchère **{bid}**", ephemeral=True)


async def setup(bot):
    await bot.add_cog(CasinoCog(bot))
    col = get_collection("role_auctions")
    if col is not None:
        cursor = col.find({"status": "active"})
        async for doc in cursor:
            aid = doc.get("_id")
            if aid:
                bot.add_view(AuctionBidView(str(aid)))
                if doc.get("join_message_id"):
                    bot.add_view(AuctionJoinView(str(aid)))
    rtc = get_collection("role_trades")
    if rtc is not None:
        async for doc in rtc.find({"status": "open"}):
            tid = doc.get("_id")
            if tid:
                bot.add_view(TradeOpenView(str(tid)))
