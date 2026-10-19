import asyncio
import collections
import time

import discord
from discord.app_commands import Choice
from discord.ext import commands
from pymongo import ReplaceOne
from pymongo.errors import BulkWriteError
from discord.ext import tasks

from .daily import ACHIEVEMENT_CATEGORIES, CATEGORY_SCHEMA, daily_rotation
from .exceptions import APIError
from .utils.db import prepare_search


class DatabaseMixin:

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

    async def upgrade_legacy_guildsync(self, guild):
        doc = await self.bot.data.guilds.get(guild.id)
        sync = doc.get("sync")
        if not sync:
            return False
        if not sync.get("setupdone") or not sync.get("on"):
            return False
        key = sync.get("leader_key", None)
        if not key:
            return False
        sync_doc = {}
        ranks_to_role_ids = sync.get("ranks")
        purge = sync.get("purge", False)
        guild_role_name = sync.get("name")
        guild_role_id = None
        gid = sync["gid"]
        base_ep = f"guild/{gid}"
        try:
            info = await self.call_api(base_ep)
        except APIError:
            print("No such guild exists. Skipping.")
            return False
        try:
            await self.call_api(base_ep + "/members", key=key)
        except APIError:
            print("Invalid key or permissions")
            return False
        tag_role = None
        if guild_role_name:
            guild_role_id = ranks_to_role_ids.pop(guild_role_name, None)
            if guild_role_id:
                tag_role = guild_role_id
        sync_doc = {
            "guild_id": guild.id,
            "enabled": {
                "tag": sync.get("guildrole", False) and sync["on"],
                "ranks": sync["on"]
            },
            "gid": gid,
            "name": info["name"],
            "tag": info["tag"],
            "tag_role": tag_role,
            "rank_roles": ranks_to_role_ids,
            "key": key
        }
        if await self.can_add_sync(guild, gid):
            await self.db.guildsyncs.insert_one(sync_doc)
            await self.bot.data.guilds.update(guild.id, {
                "guildsync.enabled": True,
                "guildsync.purge": purge
            })
            return True
        return False

    @database.command(name="update_legacy_guildsync")
    async def db_update_guildsync(self, ctx, guild: int = None):
        if not guild:
            conversions = 0
            for guild in self.bot.guilds:
                res = await self.upgrade_legacy_guildsync(guild)
                if res:
                    conversions += 1
                await asyncio.sleep(0.2)
            await ctx.send(f"{conversions} successful")
            return
        guild = self.bot.get_guild(guild)
        if not guild:
            return await ctx.send("Nope")
        done = await self.upgrade_legacy_guildsync(guild)
        if done:
            await ctx.send("Successful conversion")
        else:
            await ctx.send("Encountered error")
        pass

    @database.command(name="statistics")
    async def db_stats(self, ctx):
        """Some statistics   """
        result = await self.bot.data.users.count({"key": {"$ne": None}})
        await ctx.send("{} registered users".format(result))

    async def get_title(self, title_id):
        try:
            results = await self.db.titles.find_one({"_id": title_id})
            title = results["name"]
        except (KeyError, TypeError):
            return ""
        return title

    async def fetch_statname(self, item):
        statset = await self.db.itemstats.find_one({"_id": item})
        try:
            name = statset["name"]
        except KeyError:
            name = ""
        return name

    async def fetch_item(self, item):
        return await self.db.items.find_one({"_id": item})

    async def cache_dailies(self):
        """Cache today's and tomorrow's dailies from achievement categories."""
        ids = ",".join(str(i) for i in ACHIEVEMENT_CATEGORIES.values())
        categories = await self.call_api(f"achievements/categories?ids={ids}",
                                         schema_string=CATEGORY_SCHEMA)
        achievement_ids = {
            entry["id"]
            for category in categories
            for entry in category["achievements"] + (category.get("tomorrow") or [])
        }
        achievements = await self.call_api(
            "achievements?ids=" + ",".join(str(i) for i in sorted(achievement_ids)))
        names = {achievement["id"]: achievement["name"] for achievement in achievements}
        rotation = daily_rotation(categories, names)
        await self.bot.data.config.update({
            "cache.dailies": rotation["today"],
            "cache.dailies_tomorrow": rotation["tomorrow"]
        })

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
            print("Continents done")

    async def get_raids(self):
        config = await self.bot.data.config.get()
        return config["cache"].get("raids")

    async def cache_endpoint(self, endpoint, all_at_once=False):

        async def bulk_write(item_group):
            requests = []
            for item in itemgroup:
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
            total = len(items)
            while True:
                percentage = (counter / total) * 100
                print("Progress: {0:.1f}%".format(percentage))
                ids = ",".join(str(x) for x in items[counter:counter + 200])
                if not ids:
                    print("{} done".format(endpoint))
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
        for e in endpoints:
            try:
                await self.cache_endpoint(*e)
            except:
                msg = "Caching {} failed".format(e)
                self.log.warn(msg)
                owner = self.bot.get_user(self.bot.owner_id)
                await owner.send(msg)
        await self.db.items.create_index("name")
        await self.db.achievements.create_index("name")
        await self.db.titles.create_index("name")
        await self.db.recipes.create_index("output_item_id")
        await self.db.skins.create_index("name")
        await self.db.currencies.create_index("name")
        await self.db.skills.create_index("name")
        await self.cache_raids()
        await self.cache_pois()
        end = time.time()
        await self.bot.change_presence()
        self.bot.available = True
        print("Done")
        self.log.info("Database done! Time elapsed: {} seconds".format(end -
                                                                       start))

    async def item_autocomplete(self, interaction: discord.Interaction,
                                current: str):

        def consolidate_duplicates(items):
            unique_items = collections.OrderedDict()
            for item in items:
                item_tuple = item["name"], item["rarity"], item["type"]
                if item_tuple not in unique_items:
                    unique_items[item_tuple] = []
                unique_items[item_tuple].append(item["_id"])
            unique_list = []
            for k, v in unique_items.items():
                unique_list.append({
                    "name": k[0],
                    "rarity": k[1],
                    "ids": " ".join(v),
                    "type": k[2]
                })
            return unique_list

        query = prepare_search(current)
        query = {
            "name": query,
        }
        items = await self.db.items.find(query).to_list(25)
        items = sorted(consolidate_duplicates(current),
                       key=lambda c: c["name"])
        return [
            Choice(name=f"{it['name']} - {it['rarity']}", value=it["ids"])
            for it in items
        ]

    @tasks.loop(minutes=15)
    async def refresh_dailies(self):
        # Often enough to pick up the new rotation soon after reset
        try:
            await self.cache_dailies()
        except APIError as e:
            self.log.warning("Couldn't cache dailies: %s", e)
        except Exception:
            # An escaping exception would stop the loop for good
            self.log.exception("Exception caching dailies")

    @refresh_dailies.before_loop
    async def before_refresh_dailies(self):
        await self.bot.wait_until_ready()
