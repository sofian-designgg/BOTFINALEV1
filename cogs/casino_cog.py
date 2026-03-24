"""
Casino : mises SayuCoins, leaderboard, config (boutons), enchères de rôles, trade
"""
import random
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import InteractionType
from discord.ext import commands
from discord.ui import Button, View

from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_config, get_guild_color
from cogs.economy_cog import get_balance, add_coins, remove_coins

DEFAULT_CASINO = {
    "min_bet": 50,
    "max_bet": 50000,
    "cooldown_seconds": 15,
    "daily_game_limit": 80,
    "house_fee_percent": 5,
    "auction_channel_id": None,
    "casino_channel_id": None,
    "enabled": True,
    "games": {"slots": True, "flip": True, "blackjack": True, "pfc": True},
    "auction_fee_percent": 3,
    "bid_increment_min": 100,
}


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
    if cfg.get("casino_channel_id") and ctx.channel.id != cfg["casino_channel_id"]:
        ch = ctx.guild.get_channel(cfg["casino_channel_id"])
        return f"Jouez dans {ch.mention}." if ch else "Salon casino non configuré."
    if not cfg.get("games", {}).get(game, True):
        return "Ce jeu est désactivé."
    if bet < cfg["min_bet"]:
        return f"Mise minimale : **{cfg['min_bet']}**"
    if bet > cfg["max_bet"]:
        return f"Mise maximale : **{cfg['max_bet']}**"
    bal = await get_balance(ctx.guild.id, ctx.author.id)
    if bal < bet:
        return f"Solde insuffisant (vous avez **{bal}**)."
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


class AuctionBidView(View):
    def __init__(self, auction_id: str):
        super().__init__(timeout=None)
        self.aid = auction_id
        self.add_item(Button(label="+100", style=discord.ButtonStyle.primary, custom_id=f"auc:{auction_id}:100"))
        self.add_item(Button(label="+500", style=discord.ButtonStyle.primary, custom_id=f"auc:{auction_id}:500"))
        self.add_item(Button(label="+1000", style=discord.ButtonStyle.success, custom_id=f"auc:{auction_id}:1000"))
        self.add_item(Button(label="Achat immédiat", style=discord.ButtonStyle.danger, custom_id=f"auc:{auction_id}:buyout"))


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
            "`+casinoset fee 5` · `+casinoset auctionfee 3`\n"
            "`+casinoset bidinc 100`\n"
            "`+casinoset auctionchannel #salon` · `+casinoset casinochannel #salon` · `+casinoset resetcasinochannel`\n"
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


class TradeMoneyView(View):
    def __init__(self, guild_id: int, from_id: int, to_id: int, amount: int):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.from_id = from_id
        self.to_id = to_id
        self.amount = amount

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.to_id:
            await interaction.response.send_message("Ce trade ne vous est pas destiné.", ephemeral=True)
            return
        bal = await get_balance(self.guild_id, self.from_id)
        if bal < self.amount:
            await interaction.response.send_message("L'expéditeur n'a plus assez de monnaie.", ephemeral=True)
            return
        await remove_coins(self.guild_id, self.from_id, self.amount)
        await add_coins(self.guild_id, self.to_id, self.amount)
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"✅ Trade de **{self.amount}** SayuCoins effectué !")

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.secondary)
    async def deny(self, interaction: discord.Interaction, btn: Button):
        if interaction.user.id != self.to_id:
            await interaction.response.send_message("Ce trade ne vous est pas destiné.", ephemeral=True)
            return
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="❌ Trade refusé.", embed=None, view=self)


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
            value="`+casinolb` — Top 10 net (gains - mises enregistrés)\n`+casinostats [@membre]` — Détail perso",
            inline=False,
        )
        embed.add_field(
            name="⚙️ Config (admin)",
            value="`+casinopanel` — Boutons : aide commandes, ON/OFF, rappels salons & taxes\n"
            "`+casinoconfig` — Afficher toute la config\n"
            "`+casinoset` — minbet, maxbet, cooldown, daily, fee, auctionfee, bidinc, auctionchannel, casinochannel, game …",
            inline=False,
        )
        embed.add_field(
            name="🏷️ Enchères de rôles",
            value="`+sellrole @Rôle [prix_départ] [prix_achat_immédiat]` — Liste une vente (frais de dépôt). "
            "Boutons +100 / +500 / +1000 / achat immédiat. L’enchérisseur précédent est remboursé.\n"
            "`+auctioncancel [id]` — Annuler ta vente (admin : toutes)",
            inline=False,
        )
        embed.add_field(
            name="🤝 Trade",
            value="`+trade @membre [montant]` — Transfert proposé (boutons Accepter / Refuser)",
            inline=False,
        )
        embed.set_footer(text="Économie : daily, weekly, messages… puis casino. Configurez auctionchannel pour les ventes.")
        await ctx.send(embed=embed)

    @commands.command(name="casinoconfig")
    async def casinoconfig(self, ctx):
        cfg = await get_casino_config(ctx.guild.id)
        color = await get_guild_color(ctx.guild.id)
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
        embed.add_field(name="Frais vente enchère", value=f"{cfg.get('auction_fee_percent', 3)} %", inline=True)
        embed.add_field(name="Salon casino", value=ch_c.mention if ch_c else "Partout", inline=False)
        embed.add_field(name="Salon enchères", value=ch_a.mention if ch_a else "Non défini", inline=False)
        embed.add_field(name="Jeux", value=gtxt, inline=False)
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
        await ctx.send(embed=error_embed("Casino", "Sous-commandes : `minbet` `maxbet` `cooldown` `daily` `fee` `auctionfee` `bidinc` `auctionchannel` `casinochannel` `game`"))

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
        await ctx.send(embed=success_embed("Casino", "Jeux autorisés **partout**.", await get_guild_color(ctx.guild.id)))

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
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Enchères", "Le bot ne peut pas gérer ce rôle."))
        if role.managed:
            return await ctx.send(embed=error_embed("Enchères", "Rôle intégration / bot — interdit."))
        if role not in ctx.author.roles:
            return await ctx.send(embed=error_embed("Enchères", "Vous devez **posséder** le rôle pour le vendre."))
        if prix < 1:
            return await ctx.send(embed=error_embed("Enchères", "Prix invalide."))
        fee_pct = cfg.get("auction_fee_percent", 3)
        fee = max(1, int(prix * fee_pct / 100))
        if not await remove_coins(ctx.guild.id, ctx.author.id, fee):
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
        })
        emb = discord.Embed(
            title=f"🏷️ Enchère — {role.name}",
            description=f"Vendeur: {ctx.author.mention}\nPrix de départ: **{prix}**\n"
            f"{f'**Achat immédiat:** {buyout}' if buyout else ''}\n"
            f"Fin: <t:{int(ends.timestamp())}:R>\n`ID: {aid}`",
            color=await get_guild_color(ctx.guild.id),
        )
        view = AuctionBidView(aid)
        msg = await ch.send(embed=emb, view=view)
        self.bot.add_view(view)
        await col.update_one({"_id": aid}, {"$set": {"message_id": str(msg.id)}})
        await ctx.send(embed=success_embed("Enchères", f"Vente créée dans {ch.mention}", await get_guild_color(ctx.guild.id)))

    @commands.command(name="auctioncancel")
    async def auction_cancel(self, ctx, auction_id: str):
        col = get_collection("role_auctions")
        doc = await col.find_one({"_id": auction_id, "guild_id": str(ctx.guild.id)})
        if not doc:
            return await ctx.send(embed=error_embed("Enchères", "ID introuvable."))
        if str(ctx.author.id) != doc["seller_id"] and not ctx.author.guild_permissions.administrator:
            return await ctx.send(embed=error_embed("Enchères", "Pas votre enchère."))
        await col.update_one({"_id": auction_id}, {"$set": {"status": "cancelled"}})
        await ctx.send(embed=success_embed("Enchères", "Enchère annulée.", await get_guild_color(ctx.guild.id)))

    @commands.command(name="trade")
    async def trade(self, ctx, member: discord.Member, montant: int):
        if member.bot or member.id == ctx.author.id:
            return await ctx.send(embed=error_embed("Trade", "Membre invalide."))
        if montant < 1:
            return await ctx.send(embed=error_embed("Trade", "Montant invalide."))
        bal = await get_balance(ctx.guild.id, ctx.author.id)
        if bal < montant:
            return await ctx.send(embed=error_embed("Trade", "Solde insuffisant."))
        view = TradeMoneyView(ctx.guild.id, ctx.author.id, member.id, montant)
        emb = discord.Embed(
            title="🤝 Trade SayuCoins",
            description=f"{ctx.author.mention} propose **{montant}** à {member.mention}",
            color=await get_guild_color(ctx.guild.id),
        )
        await ctx.send(member.mention, embed=emb, view=view)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != InteractionType.component:
            return
        cid = interaction.data.get("custom_id") or ""
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
        if action == "buyout":
            if not doc.get("buyout"):
                await interaction.response.send_message("Pas d'achat immédiat sur cette vente.", ephemeral=True)
                return
            bid = doc["buyout"]
        else:
            inc = int(action)
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
        extra = f"Achat immédiat: **{bo}**\n" if bo else ""
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
