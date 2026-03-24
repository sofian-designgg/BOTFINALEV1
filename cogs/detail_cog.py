"""
Commande +detail — fiche détaillée : numéro (+help) ou nom de commande.
"""
from typing import Optional

import discord
from discord.ext import commands

from database import is_connected
from utils.command_examples import format_examples
from utils.embeds import error_embed
from utils.guild_config import get_guild_color
from utils.help_index import command_by_index, flatten_commands, index_for_command

DETAIL_EXTRA = {
    "rank": "L’XP augmente en envoyant des messages (cooldown ~60s). Les rôles avec `+xpmulti` gagnent plus vite.",
    "leaderboard": "Pagination : `+leaderboard 2` pour la page suivante.",
    "setrankchannel": "Annonces pour niveau XP, rôles paliers messages et vocal. Sans salon = pas d’annonces.",
    "addmessagerole": "Compteur = total messages (stats), tous jours confondus.",
    "addvoicerole": "Minutes cumulées en vocal (sessions enregistrées). Ex. 180 = 3h.",
    "detail": "Utilise le **numéro** affiché dans `+help` (`+detail 12`) ou le **nom** (`+detail BALANCE`).",
    "help": "Liste **toutes** les commandes numérotées par module. Puis `+detail <n>` pour la fiche.",
}


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
        """+detail [numéro ou commande] — rôle, exemples, usage."""
        if not command_query or not command_query.strip():
            color = await get_guild_color(ctx.guild.id)
            n = len(flatten_commands(self.bot))
            embed = discord.Embed(
                title="📖 Aide — +detail",
                description=(
                    f"**Méthode 1 — numéro** (comme dans `+help`) :\n"
                    f"• `{ctx.prefix}detail 5`  → fiche de la commande **n°5**\n\n"
                    f"**Méthode 2 — nom** :\n"
                    f"• `{ctx.prefix}detail balance`\n"
                    f"• `{ctx.prefix}detail casino slots`\n"
                    f"• `{ctx.prefix}detail casinoset`\n\n"
                    f"_La liste numérotée (1–{n}) est dans `+help`._"
                ),
                color=color,
            )
            await ctx.send(embed=embed)
            return

        raw = command_query.strip()
        cmd: Optional[commands.Command] = None

        if raw.isdigit():
            num = int(raw)
            cmd = command_by_index(self.bot, num)
            if cmd is None:
                mx = len(flatten_commands(self.bot))
                await ctx.send(
                    embed=error_embed(
                        "Numéro invalide",
                        f"Utilise un numéro entre **1** et **{mx}** (voir `+help`).",
                    )
                )
                return
        else:
            parts = raw.split()
            cmd = _resolve_command(self.bot, parts)

        if cmd is None:
            await ctx.send(embed=error_embed("Commande introuvable", f"Rien ne correspond à `{command_query}`."))
            return

        color = await get_guild_color(ctx.guild.id)
        qualified = cmd.qualified_name
        idx = index_for_command(self.bot, cmd)

        doc_full = (cmd.help or cmd.callback.__doc__ or "").strip()
        purpose_short = doc_full.split("\n")[0][:350] if doc_full else "Commande du bot Sayuri — voir exemples et usage ci-dessous."
        if len(purpose_short) < 8:
            purpose_short = "Commande du bot — voir la description et les exemples ci-dessous."

        long_txt = doc_full if doc_full else ""
        extra = DETAIL_EXTRA.get(qualified) or DETAIL_EXTRA.get(cmd.name)
        if extra:
            long_txt = (long_txt + "\n\n**Précisions**\n" + extra).strip() if long_txt else "**Précisions**\n" + extra

        sig = f"{ctx.prefix}{qualified}"
        if cmd.signature:
            sig += f" {cmd.signature}"

        title_num = f"#{idx} — " if idx else ""
        embed = discord.Embed(
            title=f"📖 {title_num}{qualified.upper()}",
            description=(long_txt[:3500] if long_txt else None),
            color=color,
        )
        embed.add_field(name="À quoi ça sert", value=purpose_short[:1024], inline=False)
        embed.add_field(name="Exemples", value=format_examples(ctx.prefix, cmd)[:1024], inline=False)
        embed.add_field(name="Utilisation (syntaxe)", value=f"`{sig.strip()}`"[:1024], inline=False)

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
