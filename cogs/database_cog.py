"""
Cog Base de données & Diagnostic
"""
import time
import discord
from discord.ext import commands
from database import get_collection, is_connected, get_db
from utils.embeds import success_embed, error_embed, info_embed
from config import BOT_VERSION


class DatabaseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Latence bot + MongoDB en ms"""
        try:
            before = time.perf_counter()
            msg = await ctx.send("⏳ Mesure en cours...")
            after = time.perf_counter()
            bot_latency = int((after - before) * 1000)

            mongo_start = time.perf_counter()
            connected = await is_connected()
            mongo_end = time.perf_counter()
            mongo_latency = int((mongo_end - mongo_start) * 1000) if connected else -1

            color = 0x57F287 if connected else 0xED4245
            embed = discord.Embed(
                title="📡 Latence",
                color=color,
            )
            embed.add_field(name="🤖 Bot", value=f"`{bot_latency} ms`", inline=True)
            embed.add_field(name="🗄️ MongoDB", value=f"`{mongo_latency} ms`" if mongo_latency >= 0 else "❌ Déconnecté", inline=True)
            embed.set_footer(text="━━━━━━━━━━━━━━━━━━━━")
            await msg.edit(content=None, embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="diag")
    async def diag(self, ctx):
        """Diagnostic: version, cogs chargés, commandes clés, erreurs de chargement."""
        try:
            color = 0x5865F2
            ext_fail = getattr(self.bot, "ext_failures", {}) or {}
            addcoins_cmd = self.bot.get_command("addcoins")
            econ_loaded = self.bot.get_cog("EconomyCog") is not None

            embed = discord.Embed(
                title=f"🧪 Diagnostic bot · {BOT_VERSION}",
                description="Ce message sert à vérifier si tu exécutes le bon bot et si les cogs sont chargés.",
                color=color,
            )
            embed.add_field(name="Préfixe", value=f"`{ctx.prefix}`", inline=True)
            embed.add_field(name="EconomyCog chargé", value="✅" if econ_loaded else "❌", inline=True)
            embed.add_field(name="Commande addcoins", value="✅" if addcoins_cmd else "❌", inline=True)

            if addcoins_cmd:
                embed.add_field(name="addcoins (qualified)", value=f"`{addcoins_cmd.qualified_name}`", inline=False)

            if ext_fail:
                # limite à 8 pour rester lisible
                lines = [f"- `{k}`: `{v}`" for k, v in list(ext_fail.items())[:8]]
                embed.add_field(
                    name="Erreurs chargement cogs",
                    value="\n".join(lines),
                    inline=False,
                )
                if len(ext_fail) > 8:
                    embed.add_field(name="…", value=f"+{len(ext_fail) - 8} autres", inline=False)
            else:
                embed.add_field(name="Erreurs chargement cogs", value="Aucune.", inline=False)

            embed.set_footer(text="Si addcoins=❌ : tu lances le mauvais fichier ou un cog a crash au boot.")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Diag", str(e)))

    @commands.command(name="dbstatus")
    async def dbstatus(self, ctx):
        """Vérifie la connexion MongoDB, collections, documents"""
        try:
            if not await is_connected():
                await ctx.send(embed=error_embed("MongoDB", "Connexion déconnectée."))
                return

            db = get_db()
            collections = await db.list_collection_names()
            lines = []
            total = 0
            for col_name in sorted(collections):
                col = db[col_name]
                count = await col.count_documents({})
                total += count
                lines.append(f"• **{col_name}** : {count} documents")

            embed = discord.Embed(
                title="🗄️ Statut base de données",
                description="\n".join(lines) if lines else "Aucune collection",
                color=0x57F287,
            )
            embed.add_field(name="📊 Total documents", value=str(total), inline=False)
            embed.add_field(name="✅ Statut Railway", value="Connecté" if await is_connected() else "Déconnecté", inline=False)
            embed.set_footer(text="━━━━━━━━━━━━━━━━━━━━")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="dbstats")
    async def dbstats(self, ctx):
        """Statistiques complètes : taille, guilds, users, uptime"""
        try:
            if not await is_connected():
                await ctx.send(embed=error_embed("MongoDB", "Connexion déconnectée."))
                return

            db = get_db()
            stats = await db.command("dbStats")

            guilds_col = get_collection("guild_configs")
            users_col = get_collection("users")
            if users_col is None:
                users_col = get_collection("economy")
            guild_count = await guilds_col.count_documents({}) if guilds_col is not None else 0
            user_count = await users_col.count_documents({}) if users_col is not None else 0

            uptime_sec = int(time.time() - getattr(self.bot, 'start_time', time.time()))
            uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m"

            size_mb = stats.get("dataSize", 0) / (1024 * 1024)

            embed = discord.Embed(
                title="📊 Statistiques complètes",
                color=0x5865F2,
            )
            embed.add_field(name="💾 Taille DB", value=f"{size_mb:.2f} MB", inline=True)
            embed.add_field(name="🏰 Guilds", value=str(guild_count), inline=True)
            embed.add_field(name="👥 Utilisateurs", value=str(user_count), inline=True)
            embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)
            embed.set_footer(text="━━━━━━━━━━━━━━━━━━━━")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="testdb")
    async def testdb(self, ctx):
        """Test complet : insert, read, delete"""
        try:
            if not await is_connected():
                await ctx.send(embed=error_embed("MongoDB", "Connexion déconnectée."))
                return

            col = get_collection("test_collection")
            test_doc = {"_id": "test_" + str(ctx.guild.id), "test": True}
            await col.insert_one(test_doc)
            doc = await col.find_one({"_id": test_doc["_id"]})
            await col.delete_one({"_id": test_doc["_id"]})

            if doc:
                await ctx.send(embed=success_embed("Test DB", "Insert → Read → Delete : tout fonctionne parfaitement ! ✅", 0x57F287))
            else:
                await ctx.send(embed=error_embed("Test DB", "Échec de la lecture."))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(DatabaseCog(bot))
