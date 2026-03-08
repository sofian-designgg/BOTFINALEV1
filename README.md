# 🤖 BOT ALL IN ONE — Bot Discord Complet

Bot Discord tout-en-un avec personnalisation par serveur, économie, shop, modération, XP, mini-jeux, giveaways, streaks, invitations et licence.

## 🚀 Configuration

### Variables d'environnement

Créez un fichier `.env` à la racine avec :

```
TOKEN= votre_token_discord
MONGO_URL= mongodb+srv://...
OWNER_ID= votre_discord_id
```

| Variable | Description |
|----------|-------------|
| `TOKEN` | Token du bot Discord |
| `MONGO_URL` | URI MongoDB (Atlas / Railway) |
| `OWNER_ID` | Votre ID Discord (commandes propriétaire) |

### Installation

```bash
pip install -r requirements.txt
```

### Démarrage

```bash
python main.py
```

## 📋 Liste des commandes

### ⚙️ Personnalisation (admin)
| Commande | Description |
|----------|-------------|
| `+setcolor [hex]` | Couleur principale des embeds |
| `+setbotname [nom]` | Surnom du bot |
| `+setprefix [préfixe]` | Préfixe du bot |
| `+setcurrency [nom] [emoji]` | Nom et emoji de la monnaie |
| `+setxpname [nom]` | Nom du système XP |
| `+setlevelupmsg [msg]` | Message de level-up ({user}, {level}) |
| `+setlogchannel #salon` | Salon des logs modération |
| `+setwelcomechannel #salon` | Salon de bienvenue |
| `+setwelcomemsg [msg]` | Message bienvenue ({user}, {server}) |
| `+setleavemsg [msg]` | Message départ |
| `+setmuterole @role` | Rôle mute |
| `+setadminrole @role` | Rôle admin du bot |
| `+setshopname [nom]` | Nom du shop |
| `+settings` | Affiche tous les paramètres |
| `+resetconfig` | Remet les paramètres par défaut (propriétaire serveur) |

### 🗄️ Base de données & Diagnostic
| Commande | Description |
|----------|-------------|
| `+ping` | Latence bot + MongoDB |
| `+dbstatus` | Collections, documents, statut Railway |
| `+dbstats` | Taille DB, guilds, users, uptime |
| `+testdb` | Test insert/read/delete |

### 🛡️ Modération
| Commande | Description |
|----------|-------------|
| `+ban @user [raison]` | Bannir |
| `+unban [userID] [raison]` | Débannir |
| `+kick @user [raison]` | Expulser |
| `+mute @user [durée] [raison]` | Mute (rôle) |
| `+unmute @user` | Unmute |
| `+timeout @user [durée] [raison]` | Timeout Discord |
| `+untimeout @user` | Retirer timeout |
| `+warn @user [raison]` | Avertir |
| `+warnings @user` | Liste avertissements |
| `+clearwarns @user` | Effacer avertissements |
| `+purge [nombre]` | Supprimer messages |
| `+slowmode [secondes]` | Slowmode du salon |
| `+lock` | Verrouiller salon |
| `+unlock` | Déverrouiller salon |
| `+lockdown` | Verrouiller tous les salons |
| `+unlockdown` | Déverrouiller tous |
| `+role add/remove @user @role` | Ajouter/retirer rôle |
| `+nick @user [surnom]` | Changer surnom |
| `+addword [mot]` | Mot banni |
| `+removeword [mot]` | Retirer mot banni |
| `+wordlist` | Liste mots bannis |

### ⭐ XP & Niveaux
| Commande | Description |
|----------|-------------|
| `+rank [@user]` | Rang XP avec barre progression |
| `+leaderboard [page]` | Top 10 XP |
| `+addlevelrole [niveau] @role` | Rôle récompense niveau |
| `+setxp @user [montant]` | Définir XP (admin) |
| `+resetxp @user` | Réinitialiser XP (admin) |
| `+xpmulti @role [multiplicateur]` | x2, x3 XP pour rôle |

### 🎮 Mini-jeux
| Commande | Description |
|----------|-------------|
| `+trivia` | Question à 4 boutons, gain coins |
| `+pfc [pierre/feuille/ciseaux]` | Pierre-Feuille-Ciseaux vs bot |
| `+coinflip [pile/face]` | Pile ou face |
| `+dés [faces]` | Lancer de dés (défaut: 6) |
| `+slots` | Machine à sous |
| `+blackjack` | Blackjack avec boutons |

### 📊 Statistiques
| Commande | Description |
|----------|-------------|
| `+stats [@user]` | Graphiques 7j messages + vocal |
| `+serverstats` | Graphiques serveur |
| `+ranking [messages/vocal]` | Top 10 avec barres progression |

### 💰 Économie
| Commande | Description |
|----------|-------------|
| `+balance [@user]` | Solde |
| `+daily` | Récompense quotidienne (streak) |
| `+weekly` | Récompense hebdomadaire |
| `+pay @user [montant]` | Transférer |
| `+coinstop [page]` | Top 10 richesse |
| `+addcoins @user [montant]` | Admin |
| `+removecoins @user [montant]` | Admin |

### 🛍️ Shop
| Commande | Description |
|----------|-------------|
| `+shop [page]` | Catalogue paginé |
| `+buy [item]` | Acheter |
| `+inventory [@user]` | Inventaire |
| `+additem [nom] [prix] [desc] [emoji]` | Admin |
| `+removeitem [nom]` | Admin |
| `+edititem [nom] [prix/description] [valeur]` | Admin |

### 🔑 Licence
| Commande | Description |
|----------|-------------|
| `+gencode [nombre]` | Génère codes (OWNER_ID) |
| `+redeem [code]` | Activer bot sur le serveur |
| `+listcodes` | Liste codes (propriétaire) |
| `+revoke [serverID]` | Révoquer licence |
| `+licenceinfo` | Infos licence serveur |

### 📢 Annonces
| Commande | Description |
|----------|-------------|
| `+dmall [message]` | DM à tous (confirmation) |
| `+announce #salon [message]` | Annonce stylisée |
| `+embed [titre] \| [description]` | Créer embed |

### 🎉 Giveaway
| Commande | Description |
|----------|-------------|
| `+gcreate [durée] [gagnants] [prix]` | Créer giveaway |
| `+gend [messageID]` | Terminer giveaway |
| `+greroll [messageID]` | Re-tirer gagnant |
| `+glist` | Giveaways actifs |

### ⭐ Vote / Fame
| Commande | Description |
|----------|-------------|
| `+vote @user [positive/negative]` | Voter réputation |
| `+fame [@user]` | Profil réputation |
| `+duel @user` | Duel réputation (votes) |
| `+fameleaderboard` | Top 10 réputation |

### 🔥 Streaks
| Commande | Description |
|----------|-------------|
| `+streak [@user]` | Streak actuel, objectifs |
| `+streakleaderboard` | Top 10 streaks |

### 📨 Invitations
| Commande | Description |
|----------|-------------|
| `+invites [@user]` | Nombre invitations, qui a rejoint |
| `+inviteleaderboard` | Top 10 inviters |
| `+mylink` | Lien d'invitation |
| `+createinvite [max_uses] [max_age]` | Créer lien |

## 🛠️ Setup Railway

1. Créez un projet Railway.
2. Ajoutez une base MongoDB (ou utilisez MongoDB Atlas).
3. Configurez les variables : `TOKEN`, `MONGO_URL`, `OWNER_ID`.
4. Déployez le repo avec `python main.py` comme commande de démarrage.

## 📁 Structure

```
BOT ALL IN ONE/
├── main.py           # Point d'entrée
├── config.py         # Configuration
├── database.py       # MongoDB Motor
├── utils/
│   ├── embeds.py     # Embeds stylisés
│   └── guild_config.py  # Config par serveur
└── cogs/
    ├── config_cog.py
    ├── database_cog.py
    ├── moderation_cog.py
    ├── xp_cog.py
    ├── minigames_cog.py
    ├── stats_cog.py
    ├── economy_cog.py
    ├── shop_cog.py
    ├── license_cog.py
    ├── announcements_cog.py
    ├── giveaway_cog.py
    ├── fame_cog.py
    ├── streaks_cog.py
    ├── invites_cog.py
    └── welcome_cog.py
```

## ⚠️ Licence

Sans licence active, seul `+redeem [code]` fonctionne. Générer des codes avec `+gencode` (OWNER_ID requis).
