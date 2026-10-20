"""The game data cache: items, achievements, skills and more copied from the
API into MongoDB, rebuilt when the game updates, and the owner's >database
commands."""
import logging
import time

import discord
from discord.ext import commands
from pymongo import ReplaceOne
from pymongo.errors import BulkWriteError

from .base import GW2Cog


class Cache(GW2Cog):

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)

    @commands.group(case_insensitive=True)
    @commands.is_owner()
    async def database(self, ctx):
        """Commands related to DB management"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
            return

    @database.command(name="create")
    async def db_create(self, ctx):
        """Create a new database
        """
        await self.rebuild_database()

    @database.command(name="statistics")
    async def db_stats(self, ctx):
        """Some statistics   """
        result = await self.bot.data.users.count({"key": {"$ne": None}})
        await ctx.send("{} registered users".format(result))

    async def cache_raids(self):
        raids = []
        raids_index = await self.call_api("raids")
        for raid in raids_index:
            raids.append(await self.call_api("raids/" + raid))
        await self.bot.data.config.update({"cache.raids": raids})

    async def cache_pois(self):

        async def bulk_write(group):
            requests = []
            for item in group:
                item["_id"] = item.pop("id")
                requests.append(
                    ReplaceOne({"_id": item["_id"]}, item, upsert=True))
            try:
                await self.db.pois.bulk_write(requests)
            except BulkWriteError:
                self.log.exception("BWE while caching continents")

        continents = await self.call_api("continents?ids=all")
        pois = []
        for continent in continents:
            floors = await self.call_api(
                f"continents/{continent['id']}/floors?ids=all")
            for floor in floors:
                for region in floor["regions"].values():
                    for game_map in region["maps"].values():
                        for poi in game_map["points_of_interest"].values():
                            del poi["chat_link"]
                            poi["continent_id"] = continent["id"]
                            pois.append(poi)
                            if len(pois) > 200:
                                await bulk_write(pois)
                                pois = []
        if pois:
            await bulk_write(pois)

    async def cache_endpoint(self, endpoint, all_at_once=False):

        async def bulk_write(item_group):
            requests = []
            for item in item_group:
                item["_id"] = item.pop("id")
                requests.append(
                    ReplaceOne({"_id": item["_id"]}, item, upsert=True))
            try:
                await self.db[endpoint.replace("/", "_")].bulk_write(requests)
            except BulkWriteError as e:
                self.log.exception("BWE while caching {}".format(endpoint),
                                   exc_info=e)

        items = await self.call_api(endpoint,
                                    schema_string="2021-07-15T13:00:00.000Z")
        if not all_at_once:
            counter = 0
            while True:
                ids = ",".join(str(x) for x in items[counter:counter + 200])
                if not ids:
                    break
                itemgroup = await self.call_api(
                    f"{endpoint}?ids={ids}",
                    schema_string="2021-07-15T13:00:00.000Z")
                await bulk_write(itemgroup)
                counter += 200
        else:
            itemgroup = await self.call_api(
                "{}?ids=all".format(endpoint),
                schema_string="2021-07-15T13:00:00.000Z")
            await bulk_write(itemgroup)

    async def rebuild_database(self):
        start = time.time()
        self.bot.available = False
        await self.bot.change_presence(
            activity=discord.Game(name="Rebuilding API cache"),
            status=discord.Status.dnd)
        endpoints = [["items"], ["achievements"], ["itemstats", True],
                     ["titles", True], ["recipes"], ["skins"],
                     ["currencies", True], ["skills", True],
                     ["specializations", True], ["traits", True],
                     ["minis", True], ["pvp/amulets", True],
                     ["professions", True], ["legends", True], ["pets", True],
                     ["outfits", True], ["colors", True]]
        try:
            for e in endpoints:
                try:
                    await self.cache_endpoint(*e)
                except Exception:
                    msg = "Caching {} failed".format(e)
                    self.log.exception(msg)
                    await self.tell_owner(msg)
            await self.db.items.create_index("name")
            await self.db.achievements.create_index("name")
            await self.db.titles.create_index("name")
            await self.db.recipes.create_index("output_item_id")
            await self.db.skins.create_index("name")
            await self.db.currencies.create_index("name")
            await self.db.skills.create_index("name")
            await self.cache_raids()
            await self.cache_pois()
        finally:
            await self.bot.change_presence()
            self.bot.available = True
        self.log.info("Database done! Time elapsed: %s seconds", time.time() - start)

    async def tell_owner(self, message):
        """DM the bot's owner; failures are logged."""
        try:
            owner = (self.bot.get_user(self.bot.owner_id)
                     or await self.bot.fetch_user(self.bot.owner_id))
            await owner.send(message)
        except discord.HTTPException:
            self.log.exception("Couldn't DM the owner")


async def setup(bot):
    await bot.add_cog(Cache(bot))
