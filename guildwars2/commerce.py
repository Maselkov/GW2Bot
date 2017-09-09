import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIBadRequest, APIError, APINotFound


class CommerceMixin:
    @commands.group()
    async def tp(self, ctx):
        """Commands related to tradingpost"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @tp.command(name="current")
    @commands.cooldown(1, 10, BucketType.user)
    async def tp_current(self, ctx, buys_sells):
        """Show current selling/buying transactions
        invoke with sells or buys

        Required permissions: tradingpost
        """
        user = ctx.author
        state = buys_sells.lower()
        endpoint = "commerce/transactions/current/" + state
        if state == "buys" or state == "sells":
            try:
                doc = await self.fetch_key(user, ["tradingpost"])
                results = await self.call_api(endpoint, key=doc["key"])
            except APIBadRequest:
                return await ctx.send("No ongoing transactions")
            except APIError as e:
                return await self.error_handler(ctx, e)
        else:
            return await ctx.send(
                "{0.mention}, Please us either 'sells' or 'buys' as parameter".
                format(user))
        data = discord.Embed(
            description='Current ' + state, colour=self.embed_color)
        data.set_author(
            name='Transaction overview of {0}'.format(doc["account_name"]))
        data.set_thumbnail(url=("https://wiki.guildwars2.com/"
                                "images/thumb/d/df/Black-Lion-Logo.png/"
                                "300px-Black-Lion-Logo.png"))
        data.set_footer(text="Black Lion Trading Company")
        results = results[:20]  # Only display 20 most recent transactions
        item_id = ""
        dup_item = {}
        itemlist = []
        # Collect listed items
        for result in results:
            itemdoc = await self.fetch_item(result["item_id"])
            itemlist.append(itemdoc)
            item_id += str(result["item_id"]) + ","
            if result["item_id"] not in dup_item:
                dup_item[result["item_id"]] = len(dup_item)
        # Get information about all items, doesn't matter if string ends with ,
        endpoint_listing = "commerce/listings?ids={0}".format(str(item_id))
        # Call API once for all items
        try:
            listings = await self.call_api(endpoint_listing)
        except APIError as e:
            return await self.error_handler(ctx, e)
        for result in results:
            # Store data about transaction
            index = dup_item[result["item_id"]]
            quantity = result["quantity"]
            price = result["price"]
            item_name = itemlist[index]["name"]
            offers = listings[index][state]
            max_price = offers[0]["unit_price"]
            data.add_field(
                name=item_name,
                value=str(quantity) + " x " + self.gold_to_coins(price) +
                " | Max. offer: " + self.gold_to_coins(max_price),
                inline=False)
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    @tp.command(name="price")
    @commands.cooldown(1, 15, BucketType.user)
    async def tp_price(self, ctx, *, item: str):
        """Check price of an item"""
        user = ctx.author
        choice = await self.itemname_to_id(ctx, item, user)
        if not choice:
            return
        try:
            commerce = 'commerce/prices/'
            choiceid = str(choice["_id"])
            endpoint = commerce + choiceid
            results = await self.call_api(endpoint)
        except APINotFound as e:
            return await ctx.send("{0.mention}, This item isn't on the TP."
                                  "".format(user))
        except APIError as e:
            return await self.error_handler(ctx, e)
        buyprice = results["buys"]["unit_price"]
        sellprice = results["sells"]["unit_price"]
        itemname = choice["name"]
        level = str(choice["level"])
        rarity = choice["rarity"]
        itemtype = self.gamedata["items"]["types"][choice["type"]].lower()
        description = "A level {} {} {}".format(level,
                                                rarity.lower(),
                                                itemtype.lower())
        if buyprice != 0:
            buyprice = self.gold_to_coins(buyprice)
        if sellprice != 0:
            sellprice = self.gold_to_coins(sellprice)
        if buyprice == 0:
            buyprice = 'No buy orders'
        if sellprice == 0:
            sellprice = 'No sell orders'
        data = discord.Embed(
            title=itemname,
            description=description,
            colour=self.rarity_to_color(rarity))
        if "icon" in choice:
            data.set_thumbnail(url=choice["icon"])
        data.add_field(name="Buy price", value=buyprice, inline=False)
        data.add_field(name="Sell price", value=sellprice, inline=False)
        data.set_footer(text=choice["chat_link"])
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Issue embedding data into discord")

    def gold_to_coins(self, money):
        gold, remainder = divmod(money, 10000)
        silver, copper = divmod(remainder, 100)
        if not gold:
            if not silver:
                return "{0} copper".format(copper)
            else:
                return "{0} silver and {1} copper".format(silver, copper)
        else:
            return "{0} gold, {1} silver and {2} copper".format(
                gold, silver, copper)

    def rarity_to_color(self, rarity):
        return int(self.gamedata["items"]["rarity_colors"][rarity], 0)
