"""
Commande +help : toutes les commandes (hidden incluses), numérotées, par module avec emoji.
"""
import discord
from discord.ext import commands

from database import is_connected
from utils.embeds import error_embed
from utils.guild_config import get_guild_color
from utils.help_index import build_numbered_sections, chunk_lines, flatten_commands


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
        """Affiche toutes les commandes du bot (liste numérotée, majuscules, par module)."""
        color = await get_guild_color(ctx.guild.id)
        total = len(flatten_commands(self.bot))

        intro = discord.Embed(
            title="📚 AIDE — COMMANDES",
            description=(
                f"**Préfixe :** `{ctx.prefix}`\n"
                f"**Total :** {total} commandes (numéros **1** à **{total}**).\n\n"
                "Chaque ligne : **numéro** + commande **EN MAJUSCULES** (une ligne par commande, sans lignes vides).\n\n"
                f"**Détail :** `{ctx.prefix}detail [numéro]` ou `{ctx.prefix}detail [nom]` "
                f"(ex. `{ctx.prefix}detail 5` ou `{ctx.prefix}detail BALANCE`).\n\n"
                "_Certaines commandes sont réservées au staff ou aux admins._"
            ),
            color=color,
        )
        await ctx.send(embed=intro)

        sections = build_numbered_sections(self.bot)
        fields_buffer: list[tuple[str, str]] = []
        for title, lines in sections:
            for j, chunk in enumerate(chunk_lines(lines)):
                fname = title if j == 0 else f"{title} · SUITE"
                fields_buffer.append((fname, chunk))

        idx = 0
        while idx < len(fields_buffer):
            batch = fields_buffer[idx : idx + 25]
            idx += 25
            emb = discord.Embed(title="📋 LISTE NUMÉROTÉE", color=color)
            for fname, fval in batch:
                emb.add_field(name=fname, value=fval, inline=False)
            emb.set_footer(text=f"{total} commandes · +detail <n> pour la fiche détaillée")
            await ctx.send(embed=emb)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
