"""
Casino : mises SayuCoins, leaderboard, config (boutons), enchères de rôles, trade
"""
import random
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import discord
from discord import InteractionType, SelectOption
from discord.ext import commands
from discord.ui import Button, View, Select

from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
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
    ok_cd, left = await check_casino_cooldown(ctx.guild.id, ctx.author.id, game, cfg["cooldown_seconds"])
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
        ("`+trade @Rôle *message*`", "Tu cherches un rôle : annonce + **un seul** partenaire répond ; fil privé, choix des rôles, double confirmation. `+tradecancel [id]` (auteur)."),
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
    """Menu auteur + bouton partenaire (fil privé)."""
    v = View(timeout=None)
    tid = trade_id
    sel = Select(
        custom_id=f"rtsela:{tid}",
        placeholder="Auteur : choisis le rôle que tu donnes",
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
        label="Je cède le rôle recherché (partenaire)",
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
        symbols = ["🍒", "🍋", "🍊", "💎", "7️⃣"]
        a, b, c = random.choices(symbols, k=3)
        mult = 0
        if a == b == c:
            mult = 10 if a == "7️⃣" else 8
        elif a == b or b == c or a == c:
            mult = 2
        gross = mise * mult if mult else 0
        net = await take_house_fee(gross, cfg["house_fee_percent"])
        if net:
            await add_coins(ctx.guild.id, ctx.author.id, net)
        await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=net)
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
        result = random.choice(["pile", "face"])
        win = choix == result
        gross = mise * 2 if win else 0
        net = await take_house_fee(gross, cfg["house_fee_percent"]) if win else 0
        if net:
            await add_coins(ctx.guild.id, ctx.author.id, net)
        await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=net)
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
        bot_c = random.choice(list(PFC.keys()))
        wins = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}
        if choix == bot_c:
            await add_coins(ctx.guild.id, ctx.author.id, mise)
            net = 0
            await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=0)
            msg = "Égalité — mise rendue"
        elif wins[choix] == bot_c:
            gross = mise * 2
            net = await take_house_fee(gross, cfg["house_fee_percent"])
            await add_coins(ctx.guild.id, ctx.author.id, net)
            await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=net)
            msg = "Victoire"
        else:
            net = 0
            await inc_casino_stat(ctx.guild.id, ctx.author.id, wagered=mise, won=0)
            msg = "Défaite"
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
                net = 0
                if dv > 21 or pv > dv:
                    gross = mise * 2
                    net = await take_house_fee(gross, fee)
                    await add_coins(gid, uid, net)
                elif pv == dv:
                    await add_coins(gid, uid, mise)
                    net = mise
                await inc_casino_stat(gid, uid, wagered=mise, won=net)
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

    @commands.command(name="trade")
    async def trade(self, ctx, role: discord.Role, *, message: str):
        """Annonce un trade de rôles : tu cherches @Rôle + message. Un seul partenaire peut répondre."""
        cfg = await get_casino_config(ctx.guild.id)
        err = await _must_be_channel(ctx, cfg, "channel_trade")
        if err:
            return await ctx.send(embed=error_embed("Casino", err))
        if role.is_default() or role.managed:
            return await ctx.send(embed=error_embed("Trade", "Rôle invalide (managed ou @everyone)."))
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Trade", "Le bot ne peut pas gérer ce rôle."))
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
            f"**Je cherche le rôle :** {role.mention}\n\n**Message :**\n{message[:1800]}",
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
            "wanted_role_id": str(role.id),
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
        if str(doc["claimer_role_id"]) != str(doc["wanted_role_id"]):
            return
        thread = guild.get_thread(int(doc["thread_id"])) if doc.get("thread_id") else None
        if not thread:
            return
        author = guild.get_member(int(doc["author_id"]))
        claimer = guild.get_member(int(doc["claimer_id"]))
        ar = guild.get_role(int(doc["author_role_id"]))
        wr = guild.get_role(int(doc["wanted_role_id"]))
        if not all([author, claimer, ar, wr]):
            return
        color = await get_guild_color(guild.id)
        emb = discord.Embed(
            title="🔒 Validation finale",
            description=f"**{author.display_name}** donne : {ar.mention}\n"
            f"**{claimer.display_name}** donne : {wr.mention}\n\n"
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
        wr = guild.get_role(int(doc["wanted_role_id"]))
        thread = panel_message.channel
        if not all([author, claimer, ar, wr]):
            await col.update_one(
                {"_id": trade_id},
                {"$set": {"status": "claimed", "author_conf": False, "claimer_conf": False}},
            )
            await thread.send("Membre ou rôle introuvable — échange annulé. Réessaie ou `+tradecancel`.")
            return
        if ar not in author.roles or wr not in claimer.roles:
            await col.update_one(
                {"_id": trade_id},
                {"$set": {"status": "claimed", "author_conf": False, "claimer_conf": False}},
            )
            await thread.send("Un des rôles n’est plus sur le bon membre — réessaie après correction ou annule.")
            return
        try:
            await author.remove_roles(ar, reason="Trade rôles")
            await claimer.add_roles(ar, reason="Trade rôles")
            await claimer.remove_roles(wr, reason="Trade rôles")
            await author.add_roles(wr, reason="Trade rôles")
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
            f"✅ **Échange terminé** : {author.mention} a reçu {wr.mention}, {claimer.mention} a reçu {ar.mention}."
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
        wanted = interaction.guild.get_role(int(doc["wanted_role_id"]))
        if not wanted:
            await interaction.followup.send("Rôle demandé introuvable.", ephemeral=True)
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not member or wanted not in member.roles:
            await interaction.followup.send(
                f"Il te faut le rôle {wanted.mention} pour répondre à ce trade.",
                ephemeral=True,
            )
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
        aroles = _tradable_roles(author, bot_me)
        croles = _tradable_roles(member, bot_me)
        color = await get_guild_color(interaction.guild.id)
        emb = discord.Embed(
            title="🤝 Trade — négociation",
            description=f"**Auteur :** {author.mention}\n**Partenaire :** {member.mention}\n\n"
            f"**Rôle recherché :** {wanted.mention}\n\n"
            f"**Rôles échangeables (auteur) :**\n{(', '.join(r.mention for r in aroles) or '*(aucun)*')}\n\n"
            f"**Rôles échangeables (partenaire) :**\n{(', '.join(r.mention for r in croles) or '*(aucun)*')}",
            color=color,
        )
        emb.add_field(
            name="Étapes",
            value="1. **Auteur** : menu déroulant — rôle que tu donnes.\n"
            "2. **Partenaire** : bouton **Je cède le rôle recherché**.\n"
            "3. Double confirmation pour appliquer l’échange.",
            inline=False,
        )
        if not aroles:
            await thread.send(
                embed=emb,
                content="⚠️ L’auteur n’a aucun rôle échangeable — utilise `+tradecancel` ou ajoute un rôle au bot.",
            )
            await interaction.followup.send(f"Fil créé : {thread.mention} (bloqué : pas de rôle à offrir).", ephemeral=True)
            return
        opts = [SelectOption(label=r.name[:100], value=str(r.id)) for r in aroles[:25]]
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
        if str(interaction.user.id) != doc["author_id"]:
            await interaction.response.send_message("Seul l’auteur du trade utilise ce menu.", ephemeral=True)
            return
        vals = interaction.data.get("values") or []
        if not vals:
            await interaction.response.send_message("Choix vide.", ephemeral=True)
            return
        rid = int(vals[0])
        role = interaction.guild.get_role(rid)
        author = interaction.guild.get_member(int(doc["author_id"]))
        if not role or not author or role not in author.roles or role.managed or role.is_default():
            await interaction.response.send_message("Rôle invalide.", ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("Le bot ne peut pas transférer ce rôle.", ephemeral=True)
            return
        await col.update_one({"_id": trade_id}, {"$set": {"author_role_id": str(rid)}})
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
        if str(interaction.user.id) != doc.get("claimer_id"):
            await interaction.response.send_message("Seul le partenaire utilise ce bouton.", ephemeral=True)
            return
        wanted = interaction.guild.get_role(int(doc["wanted_role_id"]))
        claimer = interaction.guild.get_member(int(doc["claimer_id"]))
        if not wanted or not claimer or wanted not in claimer.roles:
            await interaction.response.send_message("Tu n’as plus le rôle demandé.", ephemeral=True)
            return
        if wanted >= interaction.guild.me.top_role:
            await interaction.response.send_message("Le bot ne peut pas transférer ce rôle.", ephemeral=True)
            return
        await col.update_one({"_id": trade_id}, {"$set": {"claimer_role_id": str(wanted.id)}})
        await interaction.response.send_message(f"✅ Tu confirmes céder {wanted.mention}.", ephemeral=True)
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
