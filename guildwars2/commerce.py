import asyncio
import operator

import discord
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType
from discord_slash.utils.manage_components import (create_actionrow,
                                                   create_select,
                                                   create_select_option,
                                                   wait_for_component)

from .exceptions import APIBadRequest, APIError, APINotFound


class CommerceMixin:
    @cog_ext.cog_subcommand(base="tp",
                            name="selling",
                            base_description="Trading post related commands")
    async def tp_selling(self, ctx):
        """Show current selling transactions"""
        await ctx.defer()
        embed = await self.get_tp_embed(ctx, "sells")
        try:
            await ctx.send(embed=embed)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    @cog_ext.cog_subcommand(base="tp",
                            name="buying",
                            base_description="Trading post related commands")
    async def tp_buying(self, ctx):
        """Show current buying transactions"""
        await ctx.defer()
        embed = await self.get_tp_embed(ctx, "buys")
        try:
            await ctx.send(embed=embed)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    async def get_tp_embed(self, ctx, state):
        endpoint = "commerce/transactions/current/" + state
        try:
            doc = await self.fetch_key(ctx.author, ["tradingpost"])
            results = await self.call_api(endpoint, key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(description='Current ' + state,
                             colour=await self.get_embed_color(ctx))
        data.set_author(name=f'Transaction overview of {doc["account_name"]}')
        data.set_thumbnail(url=("https://wiki.guildwars2.com/"
                                "images/thumb/d/df/Black-Lion-Logo.png/"
                                "300px-Black-Lion-Logo.png"))
        data.set_footer(text="Black Lion Trading Company")
        results = results[:20]  # Only display 20 most recent transactions
        item_id = ""
        dup_item = {}
        # Collect listed items
        for result in results:
            item_id += str(result["item_id"]) + ","
            if result["item_id"] not in dup_item:
                dup_item[result["item_id"]] = len(dup_item)
        # Get information about all items, doesn't matter if string ends with ,
        endpoint_listing = "commerce/listings?ids={0}".format(str(item_id))
        # Call API once for all items
        try:
            listings = await self.call_api(endpoint_listing)
        except APIBadRequest:
            return await ctx.send("You don't have any ongoing " "transactions")
        except APIError as e:
            return await self.error_handler(ctx, e)
        for result in results:
            index = dup_item[result["item_id"]]
            price = result["price"]
            itemdoc = await self.fetch_item(result["item_id"])
            quantity = result["quantity"]
            item_name = itemdoc["name"]
            offers = listings[index][state]
            max_price = offers[0]["unit_price"]
            undercuts = 0
            op = operator.lt if state == "buys" else operator.gt
            for offer in offers:
                if op(offer["unit_price"], price):
                    break
                undercuts += offer["listings"]
            undercuts = "· Undercuts: {}".format(
                undercuts) if undercuts else ""
            if quantity == 1:
                total = ""
            else:
                total = " - Total: " + self.gold_to_coins(
                    ctx, quantity * price)
            data.add_field(name=item_name,
                           value="{} x {}{}\nMax. offer: {} {}".format(
                               quantity, self.gold_to_coins(ctx, price), total,
                               self.gold_to_coins(ctx, max_price), undercuts),
                           inline=False)
        return data

    @cog_ext.cog_subcommand(base="tp",
                            name="price",
                            base_description="Trading post related commands")
    async def tp_price(self, ctx, item: str):
        """Check price of an item"""
        flags = ["AccountBound", "SoulbindOnAcquire"]
        await ctx.defer()
        items = await self.itemname_to_id(ctx, item, flags=flags)
        if not items:
            return
        if len(items) > 1:
            options = []
            for c, m in enumerate(items):
                options.append(
                    create_select_option(m['name'],
                                         description=m["rarity"],
                                         value=c))
            select = create_select(min_values=1,
                                   max_values=1,
                                   options=options,
                                   placeholder="Select the item to search for")
            components = [create_actionrow(select)]
            msg = await ctx.send("** **", components=components)
            while True:
                try:
                    answer = await wait_for_component(self.bot,
                                                      components=components,
                                                      timeout=120)
                    await answer.defer(edit_origin=True)
                    choice = items[int(answer.selected_options[0])]
                    break
                except asyncio.TimeoutError:
                    await msg.edit(components=None)
        else:
            choice = items[0]
        try:
            commerce = 'commerce/prices/'
            choiceid = str(choice["_id"])
            endpoint = commerce + choiceid
            results = await self.call_api(endpoint)
        except APINotFound:
            return await ctx.send("This item isn't on the TP.")
        except APIError as e:
            return await self.error_handler(ctx, e)
        buyprice = results["buys"]["unit_price"]
        sellprice = results["sells"]["unit_price"]
        itemname = choice["name"]
        level = str(choice["level"])
        rarity = choice["rarity"]
        itemtype = self.gamedata["items"]["types"][choice["type"]].lower()
        description = "A level {} {} {}".format(level, rarity.lower(),
                                                itemtype.lower())
        if buyprice != 0:
            buyprice = self.gold_to_coins(ctx, buyprice)
        else:
            buyprice = "No buy orders"
        if sellprice != 0:
            sellprice = self.gold_to_coins(ctx, sellprice)
        else:
            sellprice = "No sell orders"
        data = discord.Embed(title=itemname,
                             description=description,
                             colour=self.rarity_to_color(rarity))
        if "icon" in choice:
            data.set_thumbnail(url=choice["icon"])
        data.add_field(name="Buy price", value=buyprice, inline=False)
        data.add_field(name="Sell price", value=sellprice, inline=False)
        data.set_footer(text=choice["chat_link"])
        if len(items) > 1:
            await answer.edit_origin(content=None, components=None, embed=data)
        await ctx.send(embed=data)

    @cog_ext.cog_subcommand(base="tp",
                            name="delivery",
                            base_description="Trading post related commands")
    async def tp_delivery(self, ctx):
        """Show your items awaiting in delivery box"""
        endpoint = "commerce/delivery/"
        await ctx.defer()
        try:
            doc = await self.fetch_key(ctx.author, ["tradingpost"])
            results = await self.call_api(endpoint, key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(description='Current deliveries',
                             colour=await self.get_embed_color(ctx))
        data.set_author(name=f'Delivery overview of {doc["account_name"]}')
        data.set_thumbnail(url="https://wiki.guildwars2.com/"
                           "images/thumb/d/df/Black-Lion-Logo.png"
                           "/300px-Black-Lion-Logo.png")
        data.set_footer(text="Black Lion Trading Company")
        coins = results["coins"]
        items = results["items"]
        items = items[:20]  # Get only first 20 entries
        item_quantity = []
        itemlist = []
        if coins == 0:
            gold = "Currently no coins for pickup."
        else:
            gold = self.gold_to_coins(ctx, coins)
        data.add_field(name="Coins", value=gold, inline=False)
        counter = 0
        if len(items) != 0:
            for item in items:
                item_quantity.append(item["count"])
                itemdoc = await self.fetch_item(item["id"])
                itemlist.append(itemdoc)
            for item in itemlist:
                item_name = item["name"]
                # Get quantity of items
                quantity = item_quantity[counter]
                counter += 1
                data.add_field(name=item_name,
                               value="x {0}".format(quantity),
                               inline=False)
        else:
            if coins == 0:
                return await ctx.send("Your delivery box is empty!")
            data.add_field(name="No current deliveries.",
                           value="Have fun!",
                           inline=False)
        await ctx.send(embed=data)

    def gold_to_coins(self, ctx, money):
        gold, remainder = divmod(money, 10000)
        silver, copper = divmod(remainder, 100)
        kwargs = {"fallback": True, "fallback_fmt": " {} "}
        gold = "{}{}".format(gold, self.get_emoji(ctx, "gold", **
                                                  kwargs)) if gold else ""
        silver = "{}{}".format(silver, self.get_emoji(
            ctx, "silver", **kwargs)) if silver else ""
        copper = "{}{}".format(copper, self.get_emoji(
            ctx, "copper", **kwargs)) if copper else ""
        return "".join(filter(None, [gold, silver, copper]))

    def rarity_to_color(self, rarity):
        return int(self.gamedata["items"]["rarity_colors"][rarity], 0)

    @cog_ext.cog_subcommand(base="gem",
                            name="price",
                            base_description="Gem related commands")
    async def gem_price(self, ctx, quantity: int = 400):
        """Lists current gold/gem exchange prices."""
        if quantity <= 1:
            return await ctx.send("Quantity must be higher than 1")
        await ctx.defer()
        try:
            gem_price = await self.get_gem_price(quantity)
            coin_price = await self.get_coin_price(quantity)
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(title="Currency exchange",
                             colour=await self.get_embed_color(ctx))
        data.add_field(name="{} gems would cost you".format(quantity),
                       value=self.gold_to_coins(ctx, gem_price),
                       inline=False)
        data.set_thumbnail(url="https://render.guildwars2.com/file/220061640EC"
                           "A41C0577758030357221B4ECCE62C/502065.png")
        data.add_field(name="{} gems could buy you".format(quantity),
                       value=self.gold_to_coins(ctx, coin_price),
                       inline=False)
        await ctx.send(embed=data)

    async def get_gem_price(self, quantity=400):
        endpoint = "commerce/exchange/coins?quantity=10000000"
        results = await self.call_api(endpoint)
        cost = results['coins_per_gem'] * quantity
        return cost

    async def get_coin_price(self, quantity=400):
        endpoint = "commerce/exchange/gems?quantity={}".format(quantity)
        results = await self.call_api(endpoint)
        return results["quantity"]

    @cog_ext.cog_subcommand(
        base="gem",
        name="track",
        base_description="Gem related commands",
        options=[{
            "name": "gold",
            "description":
            "Receive a notification when price of 400 gems drops below this",
            "type": SlashCommandOptionType.INTEGER,
            "required": True,
        }])
    async def gem_track(self, ctx, gold: int = 0):
        """Receive a notification when cost of 400 gems drops below given cost"""
        # if not gold:
        #     doc = await self.bot.database.get(ctx.author, self)
        #     current = doc.get("gemtrack")
        #     if current:
        #         return await ctx.send(
        #             "You'll currently be notified if "
        #             "price of 400 gems drops below **{}**".format(current //
        #                                                           10000),
        #             hidden=True)
        #     else:
        #         return await ctx.send_help(ctx.command)
        if not 0 <= gold <= 500:
            return await ctx.send(
                "Invalid value. Gold may be between 0 and 500", hidden=True)
        price = gold * 10000
        await ctx.send(
            "You will be notified when price of 400 gems "
            f"drops below {gold} gold",
            hidden=True)
        await self.bot.database.set(ctx.author, {"gemtrack": price}, self)
