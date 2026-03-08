"""
Cog Mini-jeux
"""
import random
import discord
from discord.ext import commands
from discord.ui import Button, View
from database import get_collection, is_connected
from utils.embeds import success_embed, error_embed, get_progress_bar
from utils.guild_config import get_guild_config, get_guild_color
from cogs.economy_cog import get_balance, add_coins


PFC = {"pierre": "🪨", "feuille": "📄", "ciseaux": "✂️"}
TRIVIA_REWARD = 100
COINFLIP_AMOUNT = 50
SLOTS_MULT = {"3x": 10, "2x": 2}
TRIVIA_QUESTIONS = [
    {"q": "Quelle est la capitale de la France ?", "a": ["Paris", "Lyon", "Marseille", "Bordeaux"], "c": 0},
    {"q": "Combien font 7 x 8 ?", "a": ["54", "56", "58", "60"], "c": 1},
    {"q": "Quel est le plus grand océan ?", "a": ["Atlantique", "Indien", "Pacifique", "Arctique"], "c": 2},
    {"q": "En quelle année a eu lieu la Révolution française ?", "a": ["1776", "1789", "1799", "1815"], "c": 1},
    {"q": "Quel langage utilise Discord.py ?", "a": ["JavaScript", "Python", "C++", "Java"], "c": 1},
]


class TriviaView(View):
    def __init__(self, bot, ctx, question, correct_idx, reward, timeout=20):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.ctx = ctx
        self.question = question
        self.correct_idx = correct_idx
        self.reward = reward
        self.answered = False
        for i, ans in enumerate(question["a"]):
            def make_cb(idx):
                async def cb(interaction):
                    await self.answer(interaction, idx)
                return cb
            btn = Button(label=ans[:80], style=discord.ButtonStyle.primary, custom_id=str(i))
            btn.callback = make_cb(i)
            self.add_item(btn)

    async def answer(self, interaction, idx):
        if self.answered:
            return
        self.answered = True
        for item in self.children:
            item.disabled = True
        if idx == self.correct_idx:
            await add_coins(self.ctx.guild.id, self.ctx.author.id, self.reward)
            config = await get_guild_config(self.ctx.guild.id)
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(self.ctx.guild.id)
            embed = success_embed("Correct !", f"+{self.reward} {currency_emoji}", color)
        else:
            embed = error_embed("Incorrect", f"La bonne réponse était: **{self.question['a'][self.correct_idx]}**")
        try:
            await interaction.response.edit_message(view=self)
            await self.ctx.send(embed=embed)
        except Exception:
            pass

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
            await self.ctx.send(embed=error_embed("Timeout", f"Temps écoulé. Réponse: **{self.question['a'][self.correct_idx]}**"))
        except Exception:
            pass


class MinigamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if not await is_connected():
            await ctx.send(embed=error_embed("DB", "MongoDB déconnecté."))
            return False
        return True

    @commands.command(name="trivia")
    async def trivia(self, ctx):
        """Question avec 4 boutons, gain si correct"""
        try:
            q = random.choice(TRIVIA_QUESTIONS)
            config = await get_guild_config(ctx.guild.id)
            currency_name = config.get("currency_name", "SayuCoins")
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="❓ Trivia",
                description=f"{q['q']}\n\n_Répondez avec les boutons ci-dessous (20s)_",
                color=color,
            )
            view = TriviaView(self.bot, ctx, q, q["c"], TRIVIA_REWARD)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="pfc")
    async def pfc(self, ctx, choix: str):
        """Pierre, Feuille, Ciseaux vs bot"""
        try:
            choix = choix.lower().strip()
            if choix not in PFC:
                await ctx.send(embed=error_embed("Erreur", "Choix: `pierre`, `feuille` ou `ciseaux`"))
                return
            bot_choix = random.choice(list(PFC.keys()))
            user_emoji = PFC[choix]
            bot_emoji = PFC[bot_choix]
            wins = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}
            if choix == bot_choix:
                result = "🤝 Égalité !"
            elif wins[choix] == bot_choix:
                result = "🎉 Vous gagnez !"
                await add_coins(ctx.guild.id, ctx.author.id, 25)
            else:
                result = "😢 Le bot gagne !"
            config = await get_guild_config(ctx.guild.id)
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="🪨📄✂️ Pierre Feuille Ciseaux",
                description=f"**Vous:** {user_emoji} {choix}\n**Bot:** {bot_emoji} {bot_choix}\n\n{result}",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="coinflip")
    async def coinflip(self, ctx, pari: str):
        """Pile ou Face"""
        try:
            pari = pari.lower()
            if pari not in ("pile", "face"):
                await ctx.send(embed=error_embed("Erreur", "Choix: `pile` ou `face`"))
                return
            result = random.choice(["pile", "face"])
            win = pari == result
            if win:
                await add_coins(ctx.guild.id, ctx.author.id, COINFLIP_AMOUNT)
            else:
                bal = await get_balance(ctx.guild.id, ctx.author.id)
                if bal >= COINFLIP_AMOUNT:
                    from cogs.economy_cog import remove_coins
                    await remove_coins(ctx.guild.id, ctx.author.id, COINFLIP_AMOUNT)
            emoji = "👑" if result == "pile" else "🪙"
            config = await get_guild_config(ctx.guild.id)
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="🪙 Pile ou Face",
                description=f"Résultat: **{result}** {emoji}\n\n{'✅ Vous gagnez !' if win else '❌ Vous perdez.'} {COINFLIP_AMOUNT} {config.get('currency_emoji', '💰')}",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="dés", aliases=["des"])
    async def dice(self, ctx, faces: int = 6):
        """Lancer de dés (défaut: 6 faces)"""
        try:
            faces = max(2, min(100, faces))
            result = random.randint(1, faces)
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="🎲 Lancer de dé",
                description=f"Dé **{faces}** faces : **{result}**",
                color=color,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="slots")
    async def slots(self, ctx):
        """Machine à sous - emojis, jackpot si 3 identiques"""
        try:
            symbols = ["🍒", "🍋", "🍊", "💎", "7️⃣"]
            a, b, c = random.choices(symbols, k=3)
            mult = 0
            if a == b == c:
                mult = SLOTS_MULT["3x"]
            elif a == b or b == c or a == c:
                mult = SLOTS_MULT["2x"]
            amount = 0
            config = await get_guild_config(ctx.guild.id)
            currency_emoji = config.get("currency_emoji", "💰")
            color = await get_guild_color(ctx.guild.id)
            if mult > 0:
                amount = 50 * mult
                await add_coins(ctx.guild.id, ctx.author.id, amount)
            embed = discord.Embed(
                title="🎰 Slots",
                description=f"| {a} | {b} | {c} |\n\n{'🎉 JACKPOT !' if mult == 10 else '✅ Gain !' if mult else '😢 Perdu'}",
                color=color,
            )
            if amount:
                embed.add_field(name="Gain", value=f"+{amount} {currency_emoji}", inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))

    @commands.command(name="blackjack")
    async def blackjack(self, ctx):
        """Blackjack avec boutons Tirer/Rester"""
        try:
            deck = list("234567890JQKA" * 4)
            random.shuffle(deck)
            def val(c):
                if c in "JQK0": return 10
                if c == "A": return 11
                return int(c)

            def hand_value(cards):
                v = sum(val(c) for c in cards)
                for _ in cards:
                    if "A" in cards and v > 21:
                        v -= 10
                return v

            player = [deck.pop(), deck.pop()]
            dealer = [deck.pop(), deck.pop()]

            class BJView(View):
                def __init__(self, bj_ctx, p, d, dk, timeout=30):
                    super().__init__(timeout=timeout)
                    self.ctx = bj_ctx
                    self.player = p
                    self.dealer = d
                    self.deck = dk
                    self.done = False

                @discord.ui.button(label="Tirer", style=discord.ButtonStyle.primary)
                async def hit(self, interaction, btn):
                    if interaction.user.id != self.ctx.author.id:
                        await interaction.response.send_message("Pas votre tour.", ephemeral=True)
                        return
                    self.player.append(self.deck.pop())
                    pv = hand_value(self.player)
                    if pv > 21:
                        self.done = True
                        for item in self.children:
                            item.disabled = True
                        color = await get_guild_color(self.ctx.guild.id)
                        embed = discord.Embed(title="🃏 Blackjack", description=f"**Vous:** {self.player} ({pv}) → Bust !\n**Croupier:** {self.dealer}", color=0xED4245)
                        await interaction.response.edit_message(embed=embed, view=self)
                        return
                    color = await get_guild_color(self.ctx.guild.id)
                    embed = discord.Embed(title="🃏 Blackjack", description=f"**Vous:** {self.player} ({hand_value(self.player)})\n**Croupier:** {self.dealer[0]} ?", color=color)
                    await interaction.response.edit_message(embed=embed, view=self)

                @discord.ui.button(label="Rester", style=discord.ButtonStyle.secondary)
                async def stay(self, interaction, btn):
                    if interaction.user.id != self.ctx.author.id:
                        await interaction.response.send_message("Pas votre tour.", ephemeral=True)
                        return
                    self.done = True
                    for item in self.children:
                        item.disabled = True
                    while hand_value(self.dealer) < 17:
                        self.dealer.append(self.deck.pop())
                    pv, dv = hand_value(self.player), hand_value(self.dealer)
                    if dv > 21 or pv > dv:
                        winner = "Vous gagnez !"
                        await add_coins(self.ctx.guild.id, self.ctx.author.id, 100)
                        colr = 0x57F287
                    elif pv < dv:
                        winner = "Le croupier gagne !"
                        colr = 0xED4245
                    else:
                        winner = "Égalité !"
                        colr = await get_guild_color(self.ctx.guild.id)
                    embed = discord.Embed(
                        title="🃏 Blackjack",
                        description=f"**Vous:** {self.player} ({pv})\n**Croupier:** {self.dealer} ({dv})\n\n{winner}",
                        color=colr,
                    )
                    await interaction.response.edit_message(embed=embed, view=self)

            view = BJView(ctx, player, dealer, deck)
            color = await get_guild_color(ctx.guild.id)
            embed = discord.Embed(
                title="🃏 Blackjack",
                description=f"**Vous:** {player} ({hand_value(player)})\n**Croupier:** {dealer[0]} ?",
                color=color,
            )
            await ctx.send(embed=embed, view=view)
        except Exception as e:
            await ctx.send(embed=error_embed("Erreur", str(e)))


async def setup(bot):
    await bot.add_cog(MinigamesCog(bot))
