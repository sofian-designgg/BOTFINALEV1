"""
Commande +help : liste de toutes les commandes (affichage en MAJUSCULES, lisible).
"""
from collections import defaultdict

import discord
from discord.ext import commands

from database import is_connected
from utils.embeds import error_embed
from utils.guild_config import get_guild_color


def _commands_by_cog(bot: commands.Bot) -> dict:
    by = defaultdict(list)
    for cmd in bot.walk_commands():
        if getattr(cmd, "hidden", False):
            continue
        name = cmd.cog_name or "GÉNÉRAL"
        by[name].append(cmd)
    for cmds in by.values():
        cmds.sort(key=lambda c: c.qualified_name.lower())
    return dict(sorted(by.items(), key=lambda x: x[0].lower()))


def _chunk_field_value(lines: list, max_len: int = 950) -> list[str]:
    """Découpe une liste de lignes en blocs ≤ max_len (marge sous 1024)."""
    chunks = []
    cur = []
    cur_len = 0
    for line in lines:
        add = len(line) + 2
        if cur and cur_len + add > max_len:
            chunks.append("\n\n".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += add
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="help", aliases=["aide", "commandes", "cmds"])
    async def help_command(self, ctx):
        """Affiche toutes les commandes du bot (liste en majuscules, par module)."""
        color = await get_guild_color(ctx.guild.id)
        by_cog = _commands_by_cog(self.bot)

        # Un embed d’intro + un ou plusieurs embeds de liste (limite 25 champs / embed)
        intro = discord.Embed(
            title="📚 AIDE — COMMANDES",
            description=(
                f"**Préfixe sur ce serveur :** `{ctx.prefix}`\n\n"
                "Ci-dessous, chaque commande est écrite **EN MAJUSCULES** "
                "(sous-commandes incluses, ex. `CASINO SLOTS`) pour une lecture plus claire.\n\n"
                "_Tu n’as pas accès à toutes les commandes selon ton rôle ; "
                "le bot refusera celles qui te sont interdites._"
            ),
            color=color,
        )
        await ctx.send(embed=intro)

        fields_buffer: list[tuple[str, str]] = []
        for cog_name, cmds in by_cog.items():
            lines = [f"`{c.qualified_name.upper()}`" for c in cmds]
            for i, chunk in enumerate(_chunk_field_value(lines)):
                title = cog_name.upper() if i == 0 else f"{cog_name.upper()} (SUITE)"
                fields_buffer.append((title, chunk))

        # Répartir en embeds de max 25 champs
        idx = 0
        while idx < len(fields_buffer):
            batch = fields_buffer[idx : idx + 25]
            idx += 25
            emb = discord.Embed(
                title="📋 LISTE DES COMMANDES",
                color=color,
            )
            for fname, fval in batch:
                emb.add_field(name=fname, value=fval, inline=False)
            emb.set_footer(text="Astuce : +detail <commande> pour une explication détaillée.")
            await ctx.send(embed=emb)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
