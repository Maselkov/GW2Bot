import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError


class WalletMixin:
    @commands.group()
    async def wallet(self, ctx):
        """Wallet related commands"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @wallet.command(name="currencies")
    @commands.cooldown(1, 10, BucketType.user)
    async def wallet_currencies(self, ctx):
        """Returns a list of all currencies"""
        cursor = self.db.currencies.find()
        results = []
        async for x in cursor:
            results.append(x)
        currlist = [currency["name"] for currency in results]
        output = "Available currencies are: ```"
        output += ", ".join(currlist) + "```"
        await ctx.send(output)

    @wallet.command(name="currency")
    @commands.cooldown(1, 5, BucketType.user)
    async def wallet_currency(self, ctx, *, currency: str):
        """Info about a currency. See $wallet currencies for list"""
        if currency.lower() == "gold":
            currency = "coin"
        cid = None
        async for curr in self.db.currencies.find():
            if curr["name"].lower() == currency.lower():
                cid = curr["_id"]
                desc = curr["description"]
                icon = curr["icon"]
        if not cid:
            await ctx.send("Invalid currency. See `[p]wallet currencies`")
            return
        data = discord.Embed(description="Currency", colour=self.embed_color)
        try:
            endpoint = "account/wallet"
            wallet = await self.call_api(endpoint, ctx.author, ["wallet"])
            for item in wallet:
                if item["id"] == 1 and cid == 1:
                    count = self.gold_to_coins(item["value"])
                elif item["id"] == cid:
                    count = item["value"]
            data.add_field(name="Count", value=count, inline=False)
        except:
            pass
        data.set_thumbnail(url=icon)
        data.add_field(name="Description", value=desc, inline=False)
        data.set_author(name=currency.title())
        try:
            await ctx.send(embed=data)
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
        wallet = [{
            "count": 0,
            "id": 1,
            "name": "Gold"
        }, {
            "count": 0,
            "id": 4,
            "name": "Gems"
        }, {
            "count": 0,
            "id": 2,
            "name": "Karma"
        }, {
            "count": 0,
            "id": 3,
            "name": "Laurels"
        }, {
            "count": 0,
            "id": 18,
            "name": "Transmutation Charges"
        }, {
            "count": 0,
            "id": 23,
            "name": "Spirit Shards"
        }, {
            "count": 0,
            "id": 32,
            "name": "Unbound Magic"
        }, {
            "count": 0,
            "id": 15,
            "name": "Badges of Honor"
        }, {
            "count": 0,
            "id": 16,
            "name": "Guild Commendations"
        }]
        for x in wallet:
            for curr in results:
                if curr["id"] == x["id"]:
                    x["count"] = curr["value"]
        accountname = doc["account_name"]
        data = discord.Embed(description="Wallet", colour=self.embed_color)
        for x in wallet:
            if x["name"] == "Gold":
                x["count"] = self.gold_to_coins(x["count"])
                data.add_field(name=x["name"], value=x["count"], inline=False)
            elif x["name"] == "Gems":
                data.add_field(name=x["name"], value=x["count"], inline=False)
            else:
                data.add_field(name=x["name"], value=x["count"])
        data.set_author(name=accountname)
        try:
            await ctx.send(embed=data)
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
        wallet = [{
            "count": 0,
            "id": 5,
            "name": "Ascalonian Tears"
        }, {
            "count": 0,
            "id": 6,
            "name": "Shards of Zhaitan"
        }, {
            "count": 0,
            "id": 9,
            "name": "Seals of Beetletun"
        }, {
            "count": 0,
            "id": 10,
            "name": "Manifestos of the Moletariate"
        }, {
            "count": 0,
            "id": 11,
            "name": "Deadly Blooms"
        }, {
            "count": 0,
            "id": 12,
            "name": "Symbols of Koda"
        }, {
            "count": 0,
            "id": 13,
            "name": "Flame Legion Charr Carvings"
        }, {
            "count": 0,
            "id": 14,
            "name": "Knowledge Crystals"
        }, {
            "count": 0,
            "id": 7,
            "name": "Fractal relics"
        }, {
            "count": 0,
            "id": 24,
            "name": "Pristine Fractal Relics"
        }, {
            "count": 0,
            "id": 28,
            "name": "Magnetite Shards"
        }]
        for x in wallet:
            for curr in results:
                if curr["id"] == x["id"]:
                    x["count"] = curr["value"]
        accountname = doc["account_name"]
        data = discord.Embed(description="Tokens", colour=self.embed_color)
        for x in wallet:
            if x["name"] == "Magnetite Shards":
                data.add_field(name=x["name"], value=x["count"], inline=False)
            else:
                data.add_field(name=x["name"], value=x["count"])
        data.set_author(name=accountname)
        try:
            await ctx.send(embed=data)
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
        wallet = [{
            "count": 0,
            "id": 25,
            "name": "Geodes"
        }, {
            "count": 0,
            "id": 27,
            "name": "Bandit Crests"
        }, {
            "count": 0,
            "id": 19,
            "name": "Airship Parts"
        }, {
            "count": 0,
            "id": 22,
            "name": "Lumps of Aurillium"
        }, {
            "count": 0,
            "id": 20,
            "name": "Ley Line Crystals"
        }, {
            "count": 0,
            "id": 32,
            "name": "Unbound Magic"
        }]
        for x in wallet:
            for curr in results:
                if curr["id"] == x["id"]:
                    x["count"] = curr["value"]
        accountname = doc["account_name"]
        data = discord.Embed(description="Tokens", colour=self.embed_color)
        for x in wallet:
            data.add_field(name=x["name"], value=x["count"])
        data.set_author(name=accountname)
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")
