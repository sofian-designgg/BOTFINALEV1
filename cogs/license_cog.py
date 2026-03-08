"""
Cog Licence / Redeem
"""
import secrets
import string
import discord
from discord.ext import commands
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed
from config import OWNER_ID


def generate_code() -> str:
    """Génère un code SAYU-XXXX-XXXX-XXXX"""
    chars = string.ascii_uppercase + string.digits
    p1 = ''.join(secrets.choice(chars) for _ in range(4))
    p2 = ''.join(secrets.choice(chars) for _ in range(4))
    p3 = ''.join(secrets.choice(chars) for _ in range(4))
    return f"SAYU-{p1}-{p2}-{p3}"


class LicenseCog(commands.Cog): 
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="gencode")
    async def gencode(self, ctx, amount: int = 1):
        """Génère des codes licence (propriétaire uniquement)"""
        try:
            owner = ctx.bot.owner_id or OWNER_ID
            if not owner or ctx.author.id != owner:
                await ctx.send(embed=error_embed("Accès refusé", "Réservé au propriétaire du bot. Vérifie que OWNER_ID est configuré sur Railway avec ton ID Discord."))
                return

            col = get_collection("license_codes")
            if col is None:
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return

            codes = []
            for _ in range(min(amount, 20)):
                code = generate_code()
                await col.insert_one({
                    "code": code,
                    "used": False,
                    "guild_id": None,
                    "created_at": discord.utils.utcnow()
                })
                codes.append(code)

            embed = success_embed(
                "Codes générés",
                "\n".join(f"`{c}`" for c in codes),
                0x57F287
            )
            embed.set_footer(text=f"{len(codes)} code(s) généré(s)")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="redeem")
    async def redeem(self, ctx, code: str):
        """Active le bot sur le serveur avec un code"""
        try:
            if not ctx.guild:
                await ctx.send(embed=error_embed("Erreur", "Utilisez cette commande sur un serveur."))
                return

            if not await is_connected():
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return

            col_codes = get_collection("license_codes")
            col_licenses = get_collection("licenses")
            if col_codes is None or col_licenses is None:
                await ctx.send(embed=error_embed("DB", "Base de données indisponible."))
                return

            code = code.strip().upper()
            doc = await col_codes.find_one({"code": code, "used": False})
            if not doc:
                await ctx.send(embed=error_embed("Code invalide", "Ce code n'existe pas ou a déjà été utilisé."))
                return

            await col_codes.update_one(
                {"code": code},
                {"$set": {"used": True, "guild_id": str(ctx.guild.id)}}
            )
            await col_licenses.update_one(
                {"guild_id": str(ctx.guild.id)},
                {"$set": {"active": True, "redeemed_at": discord.utils.utcnow()}},
                upsert=True
            )

            await ctx.send(embed=success_embed(
                "Licence activée",
                f"Le bot est maintenant actif sur **{ctx.guild.name}** ! 🎉",
                0x57F287
            ))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="listcodes")
    async def listcodes(self, ctx):
        """Liste tous les codes (propriétaire)"""
        try:
            owner = ctx.bot.owner_id or OWNER_ID
            if not owner or ctx.author.id != owner:
                await ctx.send(embed=error_embed("Accès refusé", "Réservé au propriétaire du bot."))
                return

            col = get_collection("license_codes")
            if col is None:
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return

            cursor = col.find({})
            codes = []
            async for doc in cursor:
                status = "✅ Utilisé" if doc.get("used") else "⏳ Disponible"
                guild = f" → {doc.get('guild_id', '-')}" if doc.get("guild_id") else ""
                codes.append(f"`{doc['code']}` {status}{guild}")

            embed = discord.Embed(
                title="🔑 Liste des codes",
                description="\n".join(codes[:30]) if codes else "Aucun code",
                color=0x5865F2,
            )
            if len(codes) > 30:
                embed.set_footer(text=f"... et {len(codes)-30} de plus")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="revoke")
    async def revoke(self, ctx, guild_id: str):
        """Révoque l'accès d'un serveur"""
        try:
            owner = ctx.bot.owner_id or OWNER_ID
            if not owner or ctx.author.id != owner:
                await ctx.send(embed=error_embed("Accès refusé", "Réservé au propriétaire du bot."))
                return

            col = get_collection("licenses")
            if col is None:
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return

            result = await col.update_one(
                {"guild_id": str(guild_id)},
                {"$set": {"active": False}}
            )
            if result.modified_count > 0:
                await ctx.send(embed=success_embed("Révoqué", f"Licence du serveur {guild_id} révoquée.", 0x57F287))
            else:
                await ctx.send(embed=error_embed("Non trouvé", f"Aucune licence pour {guild_id}."))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="licenceinfo")
    async def licenceinfo(self, ctx):
        """Affiche la licence du serveur actuel"""
        try:
            if not ctx.guild:
                return

            col = get_collection("licenses")
            if col is None:
                await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
                return

            doc = await col.find_one({"guild_id": str(ctx.guild.id)})
            if doc and doc.get("active"):
                embed = discord.Embed(
                    title="🔑 Informations licence",
                    color=0x57F287,
                )
                embed.add_field(name="Statut", value="✅ Active", inline=True)
                embed.add_field(name="Serveur", value=ctx.guild.name, inline=True)
                if doc.get("redeemed_at"):
                    embed.add_field(name="Activée le", value=discord.utils.format_dt(doc["redeemed_at"], style="R"), inline=False)
            else:
                embed = discord.Embed(
                    title="🔑 Informations licence",
                    description="❌ Aucune licence active. Utilisez `+redeem [code]` pour activer.",
                    color=0xED4245,
                )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(LicenseCog(bot))
