"""
Cog Shop - Boutique personnalisable
"""
import discord
from discord.ext import commands
from discord.ui import Button, View
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color
from cogs.economy_cog import get_balance, add_coins, remove_coins


class ShopView(View):
    def __init__(self, bot, guild_id, items, currency_name, currency_emoji, color, timeout=60):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self.items = items
        self.currency_name = currency_name
        self.currency_emoji = currency_emoji
        self.color = color
        self.page = 0
        self.add_buttons()

    def add_buttons(self):
        prev = Button(label="◀ Précédent", style=discord.ButtonStyle.secondary, custom_id="prev")
        next_btn = Button(label="Suivant ▶", style=discord.ButtonStyle.secondary, custom_id="next")
        prev.callback = self.prev_callback
        next_btn.callback = self.next_callback
        self.add_item(prev)
        self.add_item(next_btn)

    async def prev_callback(self, interaction):
        self.page = max(0, self.page - 1)
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed)

    async def next_callback(self, interaction):
        self.page = min(len(self.items) // 5, self.page + 1)
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed)

    def build_embed(self):
        start = self.page * 5
        end = min(start + 5, len(self.items))
        page_items = self.items[start:end]
        lines = []
        for i, item in enumerate(page_items, start=start + 1):
            lines.append(f"**{i}.** {item.get('emoji', '📦')} **{item['name']}** — {item['price']:,} {self.currency_name} {self.currency_emoji}\n   _{item.get('description', '')}_")
        embed = discord.Embed(
            title=f"🛒 Shop — Page {self.page + 1}/{(len(self.items)-1)//5+1}",
            description="\n\n".join(lines) if lines else "Aucun article",
            color=self.color,
        )
        embed.set_footer(text="Utilisez +buy [nom] pour acheter")
        return embed


class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="shop")
    async def shop(self, ctx, page: int = 1):
        """Catalogue paginé du shop"""
        try:
            col = get_collection("shop_items")
            cursor = col.find({"guild_id": str(ctx.guild.id)})
            items = []
            async for doc in cursor:
                items.append({
                    "name": doc["name"],
                    "price": doc["price"],
                    "description": doc.get("description", ""),
                    "emoji": doc.get("emoji", "📦"),
                })
            config = await get_guild_config(ctx.guild.id)
            shop_name = config.get("shop_name", "Sayuri Shop")
            currency_name = config.get("currency_name", "SayuCoins")
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)

            if not items:
                embed = discord.Embed(
                    title=f"🛒 {shop_name}",
                    description="Aucun article en vente.",
                    color=color,
                )
                await ctx.send(embed=embed)
                return

            view = ShopView(self.bot, ctx.guild.id, items, currency_name, currency_emoji, color)
            embed = view.build_embed()
            view.page = page - 1
            embed = view.build_embed()
            await ctx.send(embed=embed, view=view)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="buy")
    async def buy(self, ctx, *, item_name: str):
        """Achat d'un article"""
        try:
            col = get_collection("shop_items")
            doc = await col.find_one({"guild_id": str(ctx.guild.id), "name": {"$regex": item_name, "$options": "i"}})
            if not doc:
                await ctx.send(embed=error_embed("Article introuvable", f"`{item_name}`"))
                return

            price = doc["price"]
            bal = await get_balance(ctx.guild.id, ctx.author.id)
            if bal < price:
                config = await get_guild_config(ctx.guild.id)
                currency_name = config.get("currency_name", "SayuCoins")
                await ctx.send(embed=error_embed("Solde insuffisant", f"Prix: {price:,} {currency_name}. Vous: {bal:,}."))
                return

            await remove_coins(ctx.guild.id, ctx.author.id, price)
            inv_col = get_collection("inventory")
            await inv_col.update_one(
                {"guild_id": str(ctx.guild.id), "user_id": str(ctx.author.id)},
                {"$push": {"items": {"name": doc["name"], "emoji": doc.get("emoji", "📦"), "bought_at": discord.utils.utcnow()}}},
                upsert=True
            )
            config = await get_guild_config(ctx.guild.id)
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed(
                "Achat réussi",
                f"Vous avez acheté **{doc['name']}** {doc.get('emoji', '📦')} pour {price:,} {currency_emoji}",
                color
            ))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="inventory")
    async def inventory(self, ctx, member: discord.Member = None):
        """Inventaire d'un membre"""
        try:
            member = member or ctx.author
            inv_col = get_collection("inventory")
            doc = await inv_col.find_one({"guild_id": str(ctx.guild.id), "user_id": str(member.id)})
            items = doc.get("items", []) if doc else []
            color = await get_guild_color(ctx.guild.id)

            if not items:
                embed = discord.Embed(
                    title=f"🎒 Inventaire de {member.display_name}",
                    description="Aucun article.",
                    color=color,
                )
            else:
                lines = [f"{i.get('emoji', '📦')} **{i['name']}**" for i in items[:30]]
                embed = discord.Embed(
                    title=f"🎒 Inventaire de {member.display_name}",
                    description="\n".join(lines),
                    color=color,
                )
            embed.set_thumbnail(url=member.display_avatar.url)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="additem")
    @commands.has_permissions(administrator=True)
    async def additem(self, ctx, name: str, price: int, description: str, emoji: str = "📦"):
        """Ajoute un article au shop (admin)"""
        try:
            price = max(0, price)
            col = get_collection("shop_items")
            await col.insert_one({
                "guild_id": str(ctx.guild.id),
                "name": name,
                "price": price,
                "description": description,
                "emoji": emoji,
            })
            color = await get_guild_color(ctx.guild.id)
            await ctx.send(embed=success_embed("Shop", f"Article **{name}** ajouté pour {price:,}.", color))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="removeitem")
    @commands.has_permissions(administrator=True)
    async def removeitem(self, ctx, *, name: str):
        """Retire un article (admin)"""
        try:
            col = get_collection("shop_items")
            result = await col.delete_one({"guild_id": str(ctx.guild.id), "name": {"$regex": name, "$options": "i"}})
            color = await get_guild_color(ctx.guild.id)
            if result.deleted_count:
                await ctx.send(embed=success_embed("Shop", f"Article **{name}** retiré.", color))
            else:
                await ctx.send(embed=error_embed("Shop", f"Article `{name}` introuvable."))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="edititem")
    @commands.has_permissions(administrator=True)
    async def edititem(self, ctx, name: str, field: str, *, value: str):
        """Modifie un article: prix ou description (admin)"""
        try:
            col = get_collection("shop_items")
            update = {}
            if field.lower() == "prix":
                update["price"] = max(0, int(value))
            elif field.lower() in ("description", "desc"):
                update["description"] = value
            else:
                await ctx.send(embed=error_embed("Erreur", "Champ: prix ou description"))
                return
            result = await col.update_one(
                {"guild_id": str(ctx.guild.id), "name": {"$regex": name, "$options": "i"}},
                {"$set": update}
            )
            color = await get_guild_color(ctx.guild.id)
            if result.modified_count:
                await ctx.send(embed=success_embed("Shop", f"Article **{name}** mis à jour.", color))
            else:
                await ctx.send(embed=error_embed("Shop", f"Article `{name}` introuvable."))
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(ShopCog(bot))
