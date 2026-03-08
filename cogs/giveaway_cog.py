"""
Cog Giveaway
"""
import random
import re
import discord
from discord.ext import commands
from discord.ui import Button, View
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_config, get_guild_color


def parse_duration(s: str) -> int:
    s = s.lower().strip()
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    total = 0
    parts = re.findall(r"(\d+)([smhd])", s)
    for num, unit in parts:
        total += int(num) * multipliers.get(unit, 1)
    if not parts and s.isdigit():
        total = int(s)
    return total


class GiveawayButton(Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.primary, emoji="🎉", custom_id="giveaway_join")

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        col = get_collection("giveaways")
        doc = await col.find_one({"message_id": str(interaction.message.id)})
        if not doc:
            await interaction.followup.send("Giveaway introuvable.", ephemeral=True)
            return
        if doc.get("ended"):
            await interaction.followup.send("Ce giveaway est terminé.", ephemeral=True)
            return
        participants = list(doc.get("participants", []))
        uid = str(interaction.user.id)
        if uid in participants:
            participants.remove(uid)
            await col.update_one({"message_id": str(interaction.message.id)}, {"$set": {"participants": participants}})
            msg_txt = "Vous avez quitté le giveaway."
        else:
            participants.append(uid)
            await col.update_one({"message_id": str(interaction.message.id)}, {"$set": {"participants": participants}})
            msg_txt = "Vous avez rejoint le giveaway ! 🎉"
        # Actualiser l'embed
        try:
            color = await get_guild_color(interaction.guild.id)
            embed = discord.Embed(
                title="🎉 GIVEAWAY",
                description=f"**{doc['prize']}**\n\nGagnants: **{doc['winners']}**\nParticipants: **{len(participants)}**\n\nFin: <t:{int(doc['end_time'])}:R>",
                color=color,
            )
            embed.set_footer(text="Cliquez sur 🎉 pour participer !")
            view = View(timeout=None)
            view.add_item(GiveawayButton())
            await interaction.message.edit(embed=embed, view=view)
        except Exception:
            pass
        await interaction.followup.send(msg_txt, ephemeral=True)


class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="gcreate")
    @commands.has_permissions(administrator=True)
    async def gcreate(self, ctx, duration: str, winners: int, *, prize: str):
        """+gcreate [durée] [gagnants] [prix] — Crée un giveaway"""
        try:
            secs = parse_duration(duration)
            winners = max(1, min(20, winners))
            color = await get_guild_color(ctx.guild.id)

            embed = discord.Embed(
                title="🎉 GIVEAWAY",
                description=f"**{prize}**\n\nGagnants: **{winners}**\nParticipants: **0**\n\nFin: <t:{int(discord.utils.utcnow().timestamp()) + secs}:R>",
                color=color,
            )
            embed.set_footer(text="Cliquez sur 🎉 pour participer !")

            view = View(timeout=None)
            view.add_item(GiveawayButton())

            msg = await ctx.send(embed=embed, view=view)

            col = get_collection("giveaways")
            await col.insert_one({
                "message_id": str(msg.id),
                "channel_id": str(ctx.channel.id),
                "guild_id": str(ctx.guild.id),
                "prize": prize,
                "winners": winners,
                "end_time": discord.utils.utcnow().timestamp() + secs,
                "participants": [],
                "ended": False,
                "host_id": str(ctx.author.id),
            })

            await ctx.send(embed=success_embed("Giveaway créé", f"Giveaway créé ! Fin dans {duration}.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="gend")
    @commands.has_permissions(administrator=True)
    async def gend(self, ctx, message_id: int):
        """Termine un giveaway immédiatement"""
        try:
            col = get_collection("giveaways")
            doc = await col.find_one({"message_id": str(message_id), "guild_id": str(ctx.guild.id)})
            if not doc:
                await ctx.send(embed=error_embed("Erreur", "Giveaway introuvable."))
                return
            if doc.get("ended"):
                await ctx.send(embed=error_embed("Erreur", "Giveaway déjà terminé."))
                return

            participants = doc.get("participants", [])
            winners_count = min(doc["winners"], len(participants))
            if winners_count == 0:
                winners_str = "Aucun participant"
            else:
                winners = random.sample(participants, winners_count)
                winners_str = ", ".join(f"<@{w}>" for w in winners)

            await col.update_one({"message_id": str(message_id)}, {"$set": {"ended": True}})

            channel = self.bot.get_channel(int(doc["channel_id"]))
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="🎉 Giveaway terminé !",
                description=f"**Prix:** {doc['prize']}\n\n**Gagnant(s):** {winners_str}",
                color=color,
            )
            if channel:
                await channel.send(embed=embed)
            await ctx.send(embed=success_embed("Giveaway", "Giveaway terminé.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="greroll")
    @commands.has_permissions(administrator=True)
    async def greroll(self, ctx, message_id: int):
        """Re-tire un gagnant"""
        try:
            col = get_collection("giveaways")
            doc = await col.find_one({"message_id": str(message_id), "guild_id": str(ctx.guild.id)})
            if not doc or not doc.get("ended"):
                await ctx.send(embed=error_embed("Erreur", "Giveaway non trouvé ou non terminé."))
                return
            participants = doc.get("participants", [])
            if not participants:
                await ctx.send(embed=error_embed("Erreur", "Aucun participant."))
                return
            winner = random.choice(participants)
            color = await get_guild_color(ctx.guild.id)
            embed = success_embed("Re-tirage", f"Nouveau gagnant: <@{winner}> pour **{doc['prize']}** !", color)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="glist")
    @commands.has_permissions(administrator=True)
    async def glist(self, ctx):
        """Liste les giveaways actifs"""
        try:
            col = get_collection("giveaways")
            cursor = col.find({"guild_id": str(ctx.guild.id), "ended": False})
            lines = []
            async for doc in cursor:
                lines.append(f"• `{doc['message_id']}` — {doc['prize']} (fin: <t:{int(doc['end_time'])}:R>)")
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="🎉 Giveaways actifs",
                description="\n".join(lines) if lines else "Aucun giveaway actif",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(GiveawayCog(bot))
