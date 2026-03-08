"""
Cog Système d'invitations
"""
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from utils.guild_config import get_guild_config, get_guild_color
from cogs.economy_cog import add_coins

INVITE_BONUS = 100


class InvitesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._invite_cache = {}

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        for g in self.bot.guilds:
            try:
                invs = await g.invites()
                self._invite_cache[g.id] = {i.code: (i.inviter.id if i.inviter else None, i.uses) for i in invs}
            except Exception:
                self._invite_cache[g.id] = {}

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot or not member.guild:
            return
        try:
            invs_before = self._invite_cache.get(member.guild.id, {})
            invs_after = await member.guild.invites()
            for inv in invs_after:
                uses = inv.uses or 0
                before = invs_before.get(inv.code, (None, 0))[1]
                if uses > before and inv.inviter and inv.inviter.id != member.id:
                    inviter_id = inv.inviter.id
                    col = get_collection("invites")
                    await col.update_one(
                        {"guild_id": str(member.guild.id), "user_id": str(inviter_id)},
                        {
                            "$inc": {"count": 1},
                            "$push": {"joined": {"user_id": str(member.id), "at": discord.utils.utcnow()}}
                        },
                        upsert=True
                    )
                    await add_coins(member.guild.id, inviter_id, INVITE_BONUS)
                    break
            self._invite_cache[member.guild.id] = {i.code: (i.inviter.id if i.inviter else None, i.uses or 0) for i in invs_after}
        except Exception:
            pass

    @commands.command(name="invites")
    async def invites(self, ctx, member: discord.Member = None):
        """Nombre d'invitations + qui a rejoint via son lien"""
        try:
            member = member or ctx.author
            col = get_collection("invites")
            doc = await col.find_one({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
            count = doc.get("count", 0) if doc else 0
            joined = doc.get("joined", [])[-10:]  # 10 derniers
            lines = [f"<@{j['user_id']}>" for j in joined]
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title=f"📨 Invitations — {member.display_name}",
                description=f"**Total:** {count} invitation(s)",
                color=color,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            if lines:
                embed.add_field(name="Derniers membres invités", value=", ".join(lines), inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="inviteleaderboard")
    async def inviteleaderboard(self, ctx):
        """Top 10 inviters"""
        try:
            col = get_collection("invites")
            cursor = col.find({"guild_id": str(ctx.guild.id)}).sort("count", -1).limit(10)
            lines = []
            medals = ["🥇", "🥈", "🥉"]
            idx = 0
            async for doc in cursor:
                user = self.bot.get_user(int(doc["user_id"]))
                name = user.display_name if user else f"User {doc['user_id']}"
                count = doc.get("count", 0)
                medal = medals[idx] if idx < 3 else f"**{idx + 1}**"
                lines.append(f"{medal} **{name}** — {count} inv.")
                idx += 1
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="📨 Top 10 Invitations",
                description="\n".join(lines) if lines else "Aucune donnée",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="mylink")
    async def mylink(self, ctx):
        """Génère ou affiche le lien d'invitation unique de l'utilisateur"""
        try:
            invs = await ctx.guild.invites()
            user_inv = None
            for inv in invs:
                if inv.inviter and inv.inviter.id == ctx.author.id:
                    user_inv = inv
                    break
            if user_inv:
                color = await get_guild_color(ctx.guild.id)
                embed = discord.Embed(
                    title="🔗 Votre lien d'invitation",
                    description=f"[{user_inv.url}]({user_inv.url})\n\n**Utilisations:** {user_inv.uses or 0}",
                    color=color,
                )
            else:
                embed = error_embed("Lien", "Aucun lien trouvé. Utilisez `+createinvite` pour en créer un.")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="createinvite")
    async def createinvite(self, ctx, max_uses: int = 0, max_age: int = 0):
        """Crée un lien permanent unique lié à l'utilisateur"""
        try:
            inv = await ctx.channel.create_invite(max_uses=max_uses or None, max_age=max_age or 0)
            color = await get_guild_color(ctx.guild.id)
            embed = success_embed(
                "Lien créé",
                f"[{inv.url}]({inv.url})\n\nCe lien est lié à votre compte. Les membres qui rejoignent via ce lien vous seront attribués.",
                color
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(InvitesCog(bot))
