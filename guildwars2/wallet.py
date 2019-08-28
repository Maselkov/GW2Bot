import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
import re

from .exceptions import APIError
from .utils.chat import embed_list_lines

class WalletMixin:
#### For the "WALLET" command
    @commands.command(name='wallet')
    @commands.cooldown(1, 10, BucketType.user)
    async def wallet(self, ctx):
        """Shows your wallet.

        Required permissions: wallet, inventories, characters"""
        try:
            doc = await self.fetch_key(ctx.author, ['wallet'])
        except APIError as e:
            return await self.error_handler(ctx, e)
        await ctx.trigger_typing()
        ids_cur = [1, 4, 2, 3, 18, 23, 15, 16, 50, 47]
        ids_keys = [43, 40, 41, 37, 42, 38, 44, 49]
        ids_maps = [32, 45, 25, 27, 19, 22, 20, 29, 34, 35]
        ids_maps_items = [46682]
        ids_token = [5, 9, 11, 10, 13, 12, 14, 6, 7, 24]
        ids_raid = [28, 39]
        ids_l3 = [79280, 79469, 79899, 80332, 81127, 81706]
        ids_l4 = [86069, 86977, 87645, 88955, 89537, 90783]
        ids_wallet = [ids_cur, ids_keys, ids_maps, ids_token, ids_raid]
        ids_items = [ids_l3, ids_l4, ids_maps_items]

        currencies_wallet = await self.get_wallet(ctx, ids_wallet)
        currencies_items = await self.get_item_currency(ctx, ids_items)

        embed = discord.Embed(
            description="Your Wallet", colour=await self.get_embed_color(ctx))
        embed = embed_list_lines(
            embed, currencies_wallet[0], "> **CURRENCIES**", inline=True)
        embed = embed_list_lines(
            embed, currencies_wallet[3], "> **DUNGEON TOKENS**", inline=True)
        embed = embed_list_lines(
            embed, currencies_wallet[1], "> **KEYS**", inline=True)
        embed = embed_list_lines(
            embed, currencies_wallet[2][2:5] + currencies_items[2] + currencies_wallet[2][5:], "> **MAP CURRENCIES**", inline=True)
        embed = embed_list_lines(
            embed, currencies_items[0] + [currencies_wallet[2][0]], "> **LIVING SEASON 3**", inline=True)
        embed = embed_list_lines(
            embed, currencies_items[1] + [currencies_wallet[2][1]], "> **LIVING SEASON 4**", inline=True)
        embed = embed_list_lines(
            embed, currencies_wallet[4], "> **RAIDS**", inline=True)
        embed.set_author(
            name=doc['account_name'], icon_url=ctx.author.avatar_url)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links.")

    ## Searches account for items and returns list of strings
    async def get_item_currency(self, ctx, ids):
        user = ctx.author
        scopes = ['inventories', 'characters']
        lines = []
        flattened_ids = [y for x in ids for y in x]
        try:
            doc = await self.fetch_key(user, scopes)
            search_results = await self.find_items_in_account(
                ctx, flattened_ids, doc=doc)
        except APIError as e:
            return await self.error_handler(ctx, e)
        for i in range(0, len(ids)):
            lines.append([])
            for k, v in search_results.items():
                if k in ids[i]:
                    doc = await self.db.items.find_one({'_id': k})
                    name = doc['name']
                    name = re.sub('^\d+ ', '', name)
                    emoji = self.get_emoji(ctx, name)
                    lines[i].append(f"{emoji} {sum(v.values())} {name}")
        return lines
        
    ## Gets wallet information
    async def get_wallet(self, ctx, ids):
        # Returns a list of lists with currency strings
        # Difference between two lists, xs has to be the bigger one
        def get_diff(xs, ys):
            zs = []
            for x in xs:
                if x not in ys:
                    zs.append(x)
            return zs

        flattened_ids = [y for x in ids for y in x]
        try:
            doc = await self.fetch_key(ctx.author, ['wallet'])
            results = await self.call_api('account/wallet', key=doc['key'])
        except APIError as e:
            return await self.error_handler(ctx, e)
        lines = [[], [], [], [], []]
        found_ids = []
        for c in results:
            found_ids.append(c['id'])
        for id in flattened_ids:
            c_doc = await self.db.currencies.find_one({'_id': id})
            emoji = self.get_emoji(ctx, c_doc["name"])
            for i in range(0, len(lines)):
                if id in ids[i]:
                    try:
                        cur = next(
                            item for item in results if item['id'] == id)
                        value = cur['value']
                    except StopIteration:
                        value = 0
                    if c_doc['name'] == "Coin":
                        lines[i].append(f"{emoji} {self.gold_to_coins(ctx, value)} {c_doc['name']}")
                    else:
                        lines[i].append(f"{emoji} {value} {c_doc['name']}")
        return lines
