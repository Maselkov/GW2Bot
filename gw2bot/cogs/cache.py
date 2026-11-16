"""The game data cache: items, achievements, skills and more copied from the
API into MongoDB, rebuilt when the game updates, and the owner's >database
commands.

Documents are the API's English ones, with their text in German, French and
Spanish under "l10n" (see gw2bot.i18n)."""
import logging
import time

import discord
from discord.ext import commands
from pymongo import ReplaceOne
from pymongo.errors import BulkWriteError

from ..i18n import LANGUAGES, l10n_diff
from .base import GW2Cog

SCHEMA = "2021-07-15T13:00:00.000Z"
# Languages fetched besides English
OTHER_LANGUAGES = LANGUAGES[1:]
# Endpoints without text to translate: recipes and legends are ids and numbers
UNTRANSLATED = {"recipes", "legends"}
# Collections searched by name (autocomplete), in every language
NAME_INDEXED = ["items", "achievements", "titles", "skins", "currencies", "skills"]


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

        def floor_pois(floors):
            for floor in floors:
                for region in floor["regions"].values():
                    for game_map in region["maps"].values():
                        yield from game_map["points_of_interest"].values()

        continents = await self.call_api("continents?ids=all")
        pois = []
        for continent in continents:
            path = f"continents/{continent['id']}/floors?ids=all"
            # Only the names of the other languages' floors are kept: the
            # floors are big
            names = {}
            for language in OTHER_LANGUAGES:
                for poi in floor_pois(await self.call_api(path, lang=language)):
                    if "name" in poi:
                        names.setdefault(poi["id"], {})[language] = poi["name"]
            for poi in floor_pois(await self.call_api(path)):
                del poi["chat_link"]
                poi["continent_id"] = continent["id"]
                l10n = {
                    language: {"name": name}
                    for language, name in names.get(poi["id"], {}).items()
                    if name != poi.get("name")
                }
                if l10n:
                    poi["l10n"] = l10n
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

        translate = endpoint not in UNTRANSLATED
        items = await self.call_api(endpoint, schema_string=SCHEMA)
        if not all_at_once:
            counter = 0
            while True:
                ids = ",".join(str(x) for x in items[counter:counter + 200])
                if not ids:
                    break
                await bulk_write(await self.fetch_documents(f"{endpoint}?ids={ids}", translate))
                counter += 200
        else:
            await bulk_write(await self.fetch_documents(f"{endpoint}?ids=all", translate))

    async def fetch_documents(self, path, translate=True):
        """The API's documents at `path`, in English, with what differs in
        the other languages under "l10n"."""
        docs = await self.call_api(path, schema_string=SCHEMA)
        if not translate:
            return docs
        for language in OTHER_LANGUAGES:
            others = {doc["id"]: doc for doc in await self.call_api(path, schema_string=SCHEMA, lang=language)}
            for doc in docs:
                diff = l10n_diff(doc, others.get(doc["id"], {}))
                if diff:
                    doc.setdefault("l10n", {})[language] = diff
        return docs

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
            for collection in NAME_INDEXED:
                for field in ["name"] + [f"l10n.{language}.name" for language in OTHER_LANGUAGES]:
                    await self.db[collection].create_index(field)
            await self.db.recipes.create_index("output_item_id")
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
