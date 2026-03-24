"""
Commande +detail <nom> — explication détaillée d'une commande (y compris sous-commandes).
"""
from typing import Optional

import discord
from discord.ext import commands

from database import is_connected
from utils.embeds import error_embed
from utils.guild_config import get_guild_color


def _resolve_command(bot: commands.Bot, parts: list) -> Optional[commands.Command]:
    if not parts:
        return None
    cmd = bot.all_commands.get(parts[0].lower())
    if cmd is None:
        return None
    for p in parts[1:]:
        if isinstance(cmd, commands.Group):
            sub = cmd.get_command(p.lower())
            if sub is None:
                return None
            cmd = sub
        else:
            return None
    return cmd


# Textes complémentaires (la docstring reste la source principale)
DETAIL_EXTRA = {
    "rank": "Affiche ton **classement** sur le serveur et ton total **XP**. L’XP augmente en envoyant des messages "
    "(cooldown ~60s entre deux gains). Les multiplicateurs `+xpmulti` s’appliquent selon tes rôles.",
    "leaderboard": "Classement des **10** membres avec le plus d’XP. `+leaderboard 2` pour la page suivante.",
    "setrankchannel": "Définit le salon où le bot envoie les **annonces** : passage de **niveau XP**, obtention d’un "
    "**rôle palier messages** ou **vocal**. Sans salon = pas d’annonces.",
    "addmessagerole": "Quand un membre atteint **X messages au total** (compteur `message_stats`, tous jours confondus), "
    "il reçoit le rôle. Tu peux définir plusieurs paliers (rôles différents).",
    "addvoicerole": "Quand un membre cumule **X minutes** en vocal (sessions enregistrées par le bot), il reçoit le rôle. "
    "Ex. : 180 = 3h. Voir `+voiceprogress`.",
    "detail": "Affiche la **description complète** d’une commande. Ex. : `+detail rank` ou `+detail casino slots`.",
}


class DetailCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="detail", aliases=["detailed", "aidecommande", "man"])
    async def detail(self, ctx, *, command_query: str = None):
        """+detail [commande] — explication détaillée (ex: +detail rank, +detail casino slots)"""
        if not command_query or not command_query.strip():
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📖 Aide — +detail",
                description="Indique le nom d’une commande pour voir son **usage** et une **explication détaillée**.\n\n"
                "**Exemples**\n"
                f"• `{ctx.prefix}detail rank`\n"
                f"• `{ctx.prefix}detail casinoset`\n"
                f"• `{ctx.prefix}detail casino slots`\n"
                f"• `{ctx.prefix}detail addmessagerole`",
                color=color,
            )
            await ctx.send(embed=embed)
            return

        parts = command_query.strip().split()
        cmd = _resolve_command(self.bot, parts)
        if cmd is None:
            await ctx.send(embed=error_embed("Commande introuvable", f"Aucune commande : `{command_query}`"))
            return

        color = await get_guild_color(ctx.guild.id)
        qualified = cmd.qualified_name
        sig = f"{ctx.prefix}{qualified}"
        if cmd.signature:
            sig += f" {cmd.signature}"

        doc = (cmd.help or cmd.callback.__doc__ or "").strip()
        if doc:
            first = doc.split("\n", 1)[0].strip()
            long_txt = doc if len(doc) > len(first) + 5 else first
        else:
            long_txt = "*(Pas de description dans le code — demande à un admin d’ajouter une docstring.)*"

        extra = DETAIL_EXTRA.get(qualified) or DETAIL_EXTRA.get(cmd.name)
        if extra:
            long_txt = f"{long_txt}\n\n**Précisions**\n{extra}"

        embed = discord.Embed(
            title=f"📖 Commande : `{qualified}`",
            description=long_txt[:3900],
            color=color,
        )
        embed.add_field(name="Utilisation", value=f"`{sig.strip()}`"[:1024], inline=False)

        aliases = getattr(cmd, "aliases", None) or []
        if aliases:
            embed.add_field(name="Alias", value=", ".join(f"`{a}`" for a in aliases[:15]), inline=False)

        if cmd.parent:
            embed.set_footer(text=f"Sous-commande de : {cmd.parent.qualified_name}")

        if isinstance(cmd, commands.Group) and cmd.commands:
            subs = sorted(cmd.commands, key=lambda c: c.name)
            sub_list = ", ".join(f"`{s.name}`" for s in subs[:25])
            if len(subs) > 25:
                sub_list += " …"
            embed.add_field(name="Sous-commandes", value=sub_list, inline=False)

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(DetailCog(bot))
