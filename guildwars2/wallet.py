import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError
from .utils.db import prepare_search
from .utils.chat import embed_list_lines, zero_width_space


class WalletMixin:
    @commands.group(case_insensitive=True)
    async def wallet(self, ctx):
        """Wallet related commands"""
        if ctx.invoked_subcommand is None:
            try:
                length = len(ctx.prefix) + len(ctx.invoked_with)
                if length != len(ctx.message.content):
                    arg = ctx.message.content[length + 1:]
                    return await ctx.invoke(self.wallet_currency, currency=arg)
            except:
                pass
            await ctx.send_help(ctx.command)

    def get_emoji_string(self, ctx, name):
        emoji_string = name.replace(" ", "_").lower()
        emoji_string = emoji_string.replace("'", "")
        return self.get_emoji(ctx, emoji_string)

    async def get_wallet(self, ctx, ids):
        """Shows key-specific currencies

        Required permissions: wallet
        """

        # Difference between two lists, xs has to be the bigger one
        def get_diff(xs, ys):
            zs = []
            for x in xs:
                if x not in ys:
                    zs.append(x)
            return zs

        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
            results = await self.call_api("account/wallet", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        lines = []
        found_ids = []
        for c in results:
            found_ids.append(c["id"])
        diff_ids = get_diff(ids, found_ids)
        for currency in results:
            if currency["id"] not in ids:
                continue
            c_doc = await self.db.currencies.find_one({"_id": currency["id"]})
            emoji = self.get_emoji_string(ctx, c_doc["name"])
            if c_doc["name"] == "Coin":
                lines.append("{} {} {}".format(
                    emoji, self.gold_to_coins(ctx, currency["value"]),
                    c_doc["name"]))
            else:
                lines.append("{} {} {}".format(emoji, currency["value"],
                                               c_doc["name"]))
        # Currencies with value 0
        for c in diff_ids:
            c_doc = await self.db.currencies.find_one({"_id": c})
            emoji = self.get_emoji_string(ctx, c_doc["name"])
            lines.append("{} 0 {}".format(emoji, c_doc["name"]))
        return lines

    @wallet.command(name="currency")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_currency(self, ctx, *, currency):
        """Info about a currency. See $wallet currencies for list"""
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
            results = await self.call_api("account/wallet", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        currency = currency.lower()
        if currency == "gold":
            currency = "coin"
        query = {"name": prepare_search(currency)}
        count = await self.db.currencies.count_documents(query)
        cursor = self.db.currencies.find(query)
        choice = await self.selection_menu(ctx, cursor, count)
        if not choice:
            return
        embed = discord.Embed(
            title=choice["name"].title(),
            description=choice["description"],
            colour=await self.get_embed_color(ctx))
        currency_id = choice["_id"]
        for item in results:
            if item["id"] == currency_id == 1:
                count = self.gold_to_coins(ctx, item["value"])
                break
            elif item["id"] == currency_id:
                count = "{:,}".format(item["value"])
                break
            else:
                count = 0
        embed.add_field(name="Amount in wallet", value=count, inline=False)
        embed.set_thumbnail(url=choice["icon"])
        embed.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @wallet.command(name="currencies")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_currencies(self, ctx):
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        lines = []
        async for c in self.db.currencies.find({}):
            name = c["name"]
            if name == "Coin":
                emoji = self.get_emoji_string(ctx, "gold")
            else:
                emoji = self.get_emoji_string(ctx, name)
            lines.append("{} {}".format(emoji, name))
        embed = discord.Embed(
            description=zero_width_space,
            colour=await self.get_embed_color(ctx))
        embed = embed_list_lines(embed, lines, "> **CURRENCIES**", inline=True)
        embed.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @wallet.command(name="show")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_show(self, ctx):
        """Shows map-specific currencies and keys

        Required permissions: wallet
        """
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        ids_cur = [1, 4, 2, 3, 18, 23, 15, 16, 50, 47]
        ids_keys = [38, 37, 43, 41, 42, 40, 44, 49]
        ids_maps = [25, 19, 27, 22, 20, 32, 45, 34]
        ids_token = [5, 6, 9, 10, 11, 12, 13, 14, 7, 24]
        ids_raid = [28, 39]
        cur = await self.get_wallet(ctx, ids_cur)
        keys = await self.get_wallet(ctx, ids_keys)
        maps = await self.get_wallet(ctx, ids_maps)
        token = await self.get_wallet(ctx, ids_token)
        raid = await self.get_wallet(ctx, ids_raid)

        embed = discord.Embed(
            description="Wallet", colour=await self.get_embed_color(ctx))
        embed = embed_list_lines(embed, cur, "> **CURRENCIES**", inline=True)
        embed = embed_list_lines(
            embed, token, "> **DUNGEON TOKENS**", inline=True)
        embed = embed_list_lines(embed, keys, "> **KEYS**", inline=True)
        embed = embed_list_lines(embed, maps, "> **MAPS**", inline=True)
        embed = embed_list_lines(embed, raid, "> **RAIDS**")
        embed.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")
