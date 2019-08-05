import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError
from .utils.db import prepare_search


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

    def get_emoji_string(self,ctx , name):
        emoji_string = name.replace(" ", "_").lower()
        emoji_string = emoji_string.replace("'", "")
        return self.get_emoji(ctx, emoji_string)

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

    @wallet.command(name="show")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_show(self, ctx):
        """Shows most important currencies in your wallet

        Required permissions: wallet
        """
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
            results = await self.call_api("account/wallet", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        ids = [1, 4, 2, 3, 18, 23, 32, 45, 15, 16]
        embed = discord.Embed(
            description="Wallet", colour=await self.get_embed_color(ctx))
        for currency in results:
            if currency["id"] not in ids:
                continue
            c_doc = await self.db.currencies.find_one({"_id": currency["id"]})
            emoji = self.get_emoji_string(ctx, c_doc["name"])
            if c_doc["name"] == "Coin":
                embed.add_field(
                    name="Gold",
                    value=self.gold_to_coins(ctx, currency["value"]),
                    inline=False)
            elif doc["name"] == "Gem":
                embed.add_field(
                    name="Gems", value=currency["value"], inline=False)
            else:
                embed.add_field(name="{} {}".format(emoji, c_doc["name"]), value=currency["value"])
        embed.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @wallet.command(name="keys")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_keys(self, ctx):
        """Shows key-specific currencies

        Required permissions: wallet
        """
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
            results = await self.call_api("account/wallet", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        ids = [37, 38, 40, 41, 42, 43, 44]
        embed = discord.Embed(
            description="Keys", colour=await self.get_embed_color(ctx))
        for currency in results:
            if currency["id"] not in ids:
                continue
            c_doc = await self.db.currencies.find_one({"_id": currency["id"]})
            emoji = self.get_emoji_string(ctx, c_doc["name"])
            embed.add_field(name="{} {}".format(emoji, c_doc["name"]), value=currency["value"])
        embed.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @wallet.command(name="tokens")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_tokens(self, ctx):
        """Shows instance-specific currencies

        Required permissions: wallet
        """
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
            results = await self.call_api("account/wallet", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        ids = [5, 6, 9, 10, 11, 12, 13, 14, 7, 24, 28, 39]
        embed = discord.Embed(
            description="Tokens", colour=await self.get_embed_color(ctx))
        for currency in results:
            if currency["id"] not in ids:
                continue
            c_doc = await self.db.currencies.find_one({"_id": currency["id"]})
            emoji = self.get_emoji_string(ctx, c_doc["name"])
            if c_doc["name"] == "Magnetite Shard":
                embed.add_field(
                    name=c_doc["name"], value=currency["value"], inline=False)
            else:
                embed.add_field(name="{} {}".format(emoji, c_doc["name"]), value=currency["value"])
        embed.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @wallet.command(name="maps")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_maps(self, ctx):
        """Shows map-specific currencies

        Required permissions: wallet
        """
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
            results = await self.call_api("account/wallet", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        ids = [25, 27, 19, 22, 20, 32, 45, 34]
        embed = discord.Embed(
            description="Map currencies",
            colour=await self.get_embed_color(ctx))
        for currency in results:
            if currency["id"] not in ids:
                continue
            c_doc = await self.db.currencies.find_one({"_id": currency["id"]})
            embed.add_field(name=c_doc["name"], value=currency["value"])
        embed.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")
