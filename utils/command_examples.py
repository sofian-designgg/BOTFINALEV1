"""
Exemples pour +detail : texte après le préfixe (sans + en dur).
Clé = qualified_name.
"""
from typing import Dict, List

EXAMPLES_FR: Dict[str, List[str]] = {
    "balance": ["balance", "balance @membre"],
    "daily": ["daily"],
    "weekly": ["weekly"],
    "pay": ["pay @membre 500"],
    "coinstop": ["coinstop", "coinstop 2"],
    "rank": ["rank", "rank @membre"],
    "leaderboard": ["leaderboard", "leaderboard 2"],
    "setxp": ["setxp @membre 10000"],
    "stats": ["stats", "stats @membre"],
    "ranking": ["ranking messages", "ranking vocal"],
    "shop": ["shop", "shop 2"],
    "buy": ["buy Nom de l'article"],
    "inventory": ["inventory", "inventory @membre"],
    "trivia": ["trivia"],
    "pfc": ["pfc pierre"],
    "coinflip": ["coinflip pile"],
    "dés": ["dés", "dés 20"],
    "des": ["des 10"],
    "slots": ["slots"],
    "blackjack": ["blackjack"],
    "vote": ["vote @membre positive", "vote @membre neg"],
    "fame": ["fame", "fame @membre"],
    "duel": ["duel @joueur1 @joueur2"],
    "streak": ["streak", "streak @membre"],
    "invites": ["invites", "invites @membre"],
    "createinvite": ["createinvite", "createinvite 10 3600"],
    "gcreate": ["gcreate 1h 1 Nitro Discord"],
    "gend": ["gend 1234567890123456789"],
    "announce": ["announce #annonces Bienvenue à tous !"],
    "embed": ["embed Titre | Description ici"],
    "ban": ["ban @membre Spam"],
    "kick": ["kick @membre"],
    "mute": ["mute @membre 1h"],
    "timeout": ["timeout @membre 30m"],
    "purge": ["purge 50"],
    "role add": ["role add @membre @Rôle"],
    "role remove": ["role remove @membre @Rôle"],
    "nick": ["nick @membre Surnom"],
    "redeem": ["redeem SAYU-XXXX-XXXX-XXXX"],
    "casino slots": ["casino slots 100"],
    "casino flip": ["casino flip 50 pile"],
    "casino pfc": ["casino pfc 100 ciseaux"],
    "casino blackjack": ["casino blackjack 200"],
    "casinoranks me": ["casinoranks me"],
    "trade": ["trade @Fondateur Je propose ce rôle, je veux un rôle en échange"],
    "tradecancel": ["tradecancel a1b2c3d4e5"],
    "sellrole": ["sellrole @Rôle 500", "sellrole @Rôle 500 2000"],
    "auctioncancel": ["auctioncancel abcdef123456"],
    "auctionbuyout": ["auctionbuyout abcdef123456 @acheteur"],
    "settradechannel": ["settradechannel #salon-trade"],
    "casinoset auctionchannel": ["casinoset auctionchannel #enchères"],
    "casinoset setchannel slots": ["casinoset setchannel slots #slots"],
    "detail": ["detail balance", "detail 12"],
    "help": ["help"],
    "setprefix": ["setprefix !"],
    "setcurrency": ["setcurrency Or", "setcurrency SayuCoins 🪙"],
    "addallcoins": ["addallcoins 1000"],
    "addmessagerole": ["addmessagerole @Palier 500 1000"],
    "addvoicerole": ["addvoicerole @Vocal+ 180"],
    "setrankchannel": ["setrankchannel #annonces"],
}


def format_examples(prefix: str, cmd) -> str:
    """Retourne un bloc markdown d’exemples avec le bon préfixe."""
    q = cmd.qualified_name
    lines = EXAMPLES_FR.get(q)
    if not lines:
        sig = (cmd.signature or "").strip()
        if sig:
            lines = [f"{q} {sig}"]
        else:
            lines = [q]
    return "\n".join(f"`{prefix}{line}`" for line in lines)
