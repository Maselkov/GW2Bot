import operator

import discord
from discord import app_commands
from discord.app_commands import Choice
from cogs.guildwars2.utils.db import prepare_search

from .exceptions import APIBadRequest, APIError, APINotFound


class CommerceMixin:
    tp_group = app_commands.Group(name="tp",
                                  description="Trading post related commands")
    gem_group = app_commands.Group(name="gem",
                                   description="Gem related commands")

    @tp_group.command(name="selling")
    async def tp_selling(self, interaction: discord.Interaction):
        """Show current selling transactions"""
        await interaction.response.defer()
        embed = await self.get_tp_embed(interaction, "sells")
        if not embed:
            return
        await interaction.followup.send(embed=embed)

    @tp_group.command(name="buying")
    async def tp_buying(self, interaction: discord.Interaction):
        """Show current buying transactions"""
        await interaction.response.defer()
        embed = await self.get_tp_embed(interaction, "buys")
        if not embed:
            return
        await interaction.followup.send(embed=embed)

    async def get_tp_embed(self, interaction, state):
        endpoint = "commerce/transactions/current/" + state
        doc = await self.fetch_key(interaction.user, ["tradingpost"])
        results = await self.call_api(endpoint, key=doc["key"])
        data = discord.Embed(description='Current ' + state,
                             colour=await self.get_embed_color(interaction))
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
            await interaction.followup.send("You don't have any ongoing "
                                            "transactions")
            return None
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
                    interaction, quantity * price)
            data.add_field(name=item_name,
                           value="{} x {}{}\nMax. offer: {} {}".format(
                               quantity,
                               self.gold_to_coins(interaction, price), total,
                               self.gold_to_coins(interaction,
                                                  max_price), undercuts),
                           inline=False)
        return data

    async def tp_autocomplete(self, interaction: discord.Interaction,
                              current: str):
        if not current:
            return []
        query = prepare_search(current)
        query = {
            "name": query,
            "flags": {
                "$nin": ["AccountBound", "SoulbindOnAcquire"]
            }
        }
        items = await self.db.items.find(query).to_list(25)
        items = sorted(items, key=lambda c: c["name"])
        return [Choice(name=it["name"], value=str(it["_id"])) for it in items]

    @tp_group.command(name="price")
    @app_commands.autocomplete(item=tp_autocomplete)
    @app_commands.describe(
        item="Specify the name of an item to check the price of")
    async def tp_price(self, interaction: discord.Interaction, item: str):
        """Check price of an item"""
        await interaction.response.defer()
        try:
            commerce = 'commerce/prices/'
            endpoint = commerce + item
            results = await self.call_api(endpoint)
        except APINotFound:
            return await interaction.followup.send("This item isn't on the TP."
                                                   )
        except APIError:
            raise
        choice = await self.db.items.find_one({"_id": int(item)})
        buyprice = results["buys"]["unit_price"]
        sellprice = results["sells"]["unit_price"]
        itemname = choice["name"]
        level = str(choice["level"])
        rarity = choice["rarity"]
        itemtype = self.gamedata["items"]["types"][choice["type"]].lower()
        description = "A level {} {} {}".format(level, rarity.lower(),
                                                itemtype.lower())
        if buyprice != 0:
            buyprice = self.gold_to_coins(interaction, buyprice)
        else:
            buyprice = "No buy orders"
        if sellprice != 0:
            sellprice = self.gold_to_coins(interaction, sellprice)
        else:
            sellprice = "No sell orders"
        embed = discord.Embed(title=itemname,
                              description=description,
                              colour=self.rarity_to_color(rarity))
        if "icon" in choice:
            embed.set_thumbnail(url=choice["icon"])
        embed.add_field(name="Buy price", value=buyprice, inline=False)
        embed.add_field(name="Sell price", value=sellprice, inline=False)
        embed.set_footer(text=choice["chat_link"])
        await interaction.followup.send(embed=embed)

    @tp_group.command(name="delivery")
    async def tp_delivery(self, interaction: discord.Interaction):
        """Show your items awaiting in delivery box"""
        endpoint = "commerce/delivery/"
        await interaction.response.defer()
        doc = await self.fetch_key(interaction.user, ["tradingpost"])
        results = await self.call_api(endpoint, key=doc["key"])
        data = discord.Embed(description='Current deliveries',
                             colour=await self.get_embed_color(interaction))
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
            gold = self.gold_to_coins(interaction, coins)
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
                return await interaction.followup.send(
                    "Your delivery box is empty!")
            data.add_field(name="No current deliveries.",
                           value="Have fun!",
                           inline=False)
        await interaction.followup.send(embed=data)

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

    @gem_group.command(name="price")
    @app_commands.describe(
        quantity="The number of gems to evaluate (default is 400)")
    async def gem_price(self,
                        interaction: discord.Interaction,
                        quantity: int = 400):
        """Lists current gold/gem exchange prices."""
        if quantity <= 1:
            return await interaction.followup.send(
                "Quantity must be higher than 1")
        await interaction.response.defer()
        gem_price = await self.get_gem_price(quantity)
        coin_price = await self.get_coin_price(quantity)
        data = discord.Embed(title="Currency exchange",
                             colour=await self.get_embed_color(interaction))
        data.add_field(name="{} gems would cost you".format(quantity),
                       value=self.gold_to_coins(interaction, gem_price),
                       inline=False)
        data.set_thumbnail(url="https://render.guildwars2.com/file/220061640EC"
                           "A41C0577758030357221B4ECCE62C/502065.png")
        data.add_field(name="{} gems could buy you".format(quantity),
                       value=self.gold_to_coins(interaction, coin_price),
                       inline=False)
        await interaction.followup.send(embed=data)

    async def get_gem_price(self, quantity=400):
        endpoint = "commerce/exchange/coins?quantity=10000000"
        results = await self.call_api(endpoint)
        cost = results['coins_per_gem'] * quantity
        return cost

    async def get_coin_price(self, quantity=400):
        endpoint = "commerce/exchange/gems?quantity={}".format(quantity)
        results = await self.call_api(endpoint)
        return results["quantity"]

    @gem_group.command(name="track")
    @app_commands.describe(gold="Receive a notification when price of 400 "
                           "gems drops below this amount. Set to 0 to disable")
    async def gem_track(self, interaction: discord.Interaction, gold: int):
        """Receive a notification when cost of 400 gems drops below given cost
        """
        if not 0 <= gold <= 500:
            return await interaction.response.send_message(
                "Invalid value. Gold may be between 0 and 500", ephemeral=True)
        price = gold * 10000
        await interaction.response.send_message(
            "You will be notified when price of 400 gems "
            f"drops below {gold} gold",
            ephemeral=True)
        await self.bot.database.set(interaction.user, {"gemtrack": price},
                                    self)
