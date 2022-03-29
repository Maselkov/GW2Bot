import random
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType

from .exceptions import APIError
from .utils.chat import embed_list_lines
from .utils.db import prepare_search


class WalletMixin:
    async def get_wallet(self, ctx, ids):
        flattened_ids = [y for x in ids for y in x]
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
            results = await self.call_api("account/wallet", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        lines = [[] for i in range(len(ids))]
        found_ids = []
        for c in results:
            found_ids.append(c["id"])
        for id in flattened_ids:
            c_doc = await self.db.currencies.find_one({"_id": id})
            emoji = self.get_emoji(ctx, c_doc["name"])
            for i in range(0, len(lines)):
                if id in ids[i]:
                    try:
                        cur = next(item for item in results
                                   if item["id"] == id)
                        value = cur["value"]
                    except StopIteration:
                        value = 0
                    if c_doc["name"] == "Coin":
                        lines[i].append("{} {} {}".format(
                            emoji, self.gold_to_coins(ctx, value),
                            c_doc["name"]))
                    else:
                        lines[i].append("{} {} {}".format(
                            emoji, value, c_doc["name"]))
        return lines

    # Searches account for items and returns list of strings
    async def get_item_currency(self, ctx, ids):
        user = ctx.author
        scopes = ["inventories", "characters"]
        lines = []
        flattened_ids = [y for x in ids for y in x]
        doc = await self.fetch_key(user, scopes)
        search_results = await self.find_items_in_account(ctx,
                                                          flattened_ids,
                                                          doc=doc)

        for i in range(0, len(ids)):
            lines.append([])
            for k, v in search_results.items():
                if k in ids[i]:
                    doc = await self.db.items.find_one({"_id": k})
                    name = doc["name"]
                    name = re.sub('^\d+ ', '', name)
                    emoji = self.get_emoji(ctx, name)
                    lines[i].append("{} {} {}".format(emoji, sum(v.values()),
                                                      name))
        return lines

    @cog_ext.cog_slash(options=[{
        "name": "currency",
        "description":
        "The specific currency to search for. Leave blank for general overview.",
        "type": SlashCommandOptionType.STRING,
        "required": False,
    }])
    async def wallet(self, ctx, *, currency=None):
        """Shows your wallet"""
        await ctx.defer()
        try:
            doc = await self.fetch_key(ctx.author, ["wallet"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        if currency:
            try:
                results = await self.call_api("account/wallet", key=doc["key"])
            except APIError as e:
                return await self.error_handler(ctx, e)
            currency = currency.lower()
            if currency == "gold":
                currency = "coin"
            query = {"name": prepare_search(currency)}
            count = await self.db.currencies.count_documents(query)
            cursor = self.db.currencies.find(query)
            answer = None
            choice = await self.selection_menu(ctx, cursor, count)
            if type(choice) is tuple:
                choice, answer = choice
            if choice:
                embed = discord.Embed(title=choice["name"].title(),
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
                embed.add_field(name="Amount in wallet",
                                value=count,
                                inline=False)
                embed.set_thumbnail(url=choice["icon"])
                embed.set_author(name=doc["account_name"],
                                 icon_url=ctx.author.avatar_url)
                embed.set_footer(text=self.bot.user.name,
                                 icon_url=self.bot.user.avatar_url)
                if answer:
                    return await answer.edit_origin(embed=embed,
                                                    components=None)
                return await ctx.send(embed=embed)
        ids_cur = [1, 4, 2, 3, 18, 23, 16, 50, 47]
        ids_keys = [43, 40, 41, 37, 42, 38, 44, 49, 51]
        ids_maps = [32, 45, 25, 27, 19, 22, 20, 29, 34, 35]
        ids_wvw_cur = [15, 26, 31, 36, 65]
        ids_pvp_cur = [33]
        ids_pvp = [70820]
        ids_maps_items = [46682]
        ids_token = [5, 9, 11, 10, 13, 12, 14, 6, 7, 24, 59]
        ids_raid = [28, 39]
        ids_l3 = [79280, 79469, 79899, 80332, 81127, 81706]
        ids_l4 = [86069, 86977, 87645, 88955, 89537, 90783]
        ids_ibs = [92072, 92272]
        ids_ibs_cur = [58, 60]
        ids_eod_cur = [61, 62, 64, 67, 68]
        ids_strikes_cur = [53, 55, 57, 54]
        ids_wallet = [
            ids_cur, ids_keys, ids_maps, ids_token, ids_raid, ids_ibs_cur, 
            ids_strikes_cur, ids_eod_cur, ids_wvw_cur, ids_pvp_cur
        ]
        ids_items = [ids_l3, ids_l4, ids_ibs, ids_maps_items, ids_pvp]
        try:
            currencies_wallet = await self.get_wallet(ctx, ids_wallet)
            currencies_items = await self.get_item_currency(ctx, ids_items)
        except APIError as e:
            return await self.error_handler(ctx, e)
        embed = discord.Embed(description="Wallet",
                              colour=await self.get_embed_color(ctx))
        embed = embed_list_lines(embed,
                                 currencies_wallet[0],
                                 "> **CURRENCIES**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_wallet[3],
                                 "> **DUNGEON TOKENS**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_wallet[1],
                                 "> **KEYS**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_wallet[2][2:5] +
                                 currencies_wallet[2][5:],
                                 "> **MAP CURRENCIES**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_items[0] +
                                 [currencies_wallet[2][0]],
                                 "> **LIVING SEASON 3**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_items[1] +
                                 [currencies_wallet[2][1]],
                                 "> **LIVING SEASON 4**",
                                 inline=True)
        saga_title = "ICEBROOD SAGA"
        expansion_content = random.random() >= 0.85
        if expansion_content:
            saga_title = "EXPANSION LEVEL CONTENT"
        embed = embed_list_lines(embed,
                                 currencies_items[2] + currencies_wallet[5],
                                 f"> **{saga_title}**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_wallet[7],
                                 "> **END OF DRAGONS**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_wallet[6],
                                 "> **STRIKE MISSIONS**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_wallet[8] + currencies_items[4] + 
                                 currencies_wallet[9],
                                 "> **COMPETITION**",
                                 inline=True)
        embed = embed_list_lines(embed,
                                 currencies_wallet[4],
                                 "> **RAIDS**",
                                 inline=True)
        embed.set_author(name=doc["account_name"],
                         icon_url=ctx.author.avatar_url)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.avatar_url)
        await ctx.send(embed=embed)
