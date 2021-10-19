import asyncio
import collections
import datetime
import re
import time
from unicodedata import name

import discord
from discord.ext import commands
from discord_slash.context import ComponentContext
from discord_slash.utils.manage_components import (create_actionrow,
                                                   create_select,
                                                   create_select_option,
                                                   wait_for_component)
from pymongo import ReplaceOne
from pymongo.errors import BulkWriteError

from .exceptions import APIError, APIKeyError


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
        doc = await self.bot.database.get(guild, self)
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
            await self.bot.database.set(guild, {
                "guildsync.enabled": True,
                "guildsync.purge": purge
            }, self)
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

    @database.command(name="getwvwdata")
    async def db_getwvwdata(self, ctx, guild: int = None):
        """Get historical wvw population data. Might not work"""
        await self.get_historical_world_pop_data()
        await ctx.send("Done")

    @database.command(name="statistics")
    async def db_stats(self, ctx):
        """Some statistics   """
        result = await self.bot.database.users.count_documents(
            {"cogs.GuildWars2.key": {
                "$ne": None
            }}, self)
        await ctx.send("{} registered users".format(result))

    async def get_title(self, title_id):
        try:
            results = await self.db.titles.find_one({"_id": title_id})
            title = results["name"]
        except (KeyError, TypeError):
            return ""
        return title

    async def get_world_name(self, wid):
        try:
            doc = await self.db.worlds.find_one({"_id": wid})
            name = doc["name"]
        except KeyError:
            name = None
        return name

    async def get_world_id(self, world):
        world = re.escape(world)
        world = "^" + world + "$"
        search = re.compile(world, re.IGNORECASE)
        if world is None:
            return None
        doc = await self.db.worlds.find_one({"name": search})
        if not doc:
            return None
        return doc["_id"]

    async def fetch_statname(self, item):
        statset = await self.db.itemstats.find_one({"_id": item})
        try:
            name = statset["name"]
        except:
            name = ""
        return name

    async def fetch_item(self, item):
        return await self.db.items.find_one({"_id": item})

    async def fetch_key(self, user, scopes=None):
        doc = await self.bot.database.get_user(user, self)
        if not doc or "key" not in doc or not doc["key"]:
            raise APIKeyError(
                "No API key associated with {.mention}. "
                "Add your key using `$key add` command. If you don't know "
                "how, the command includes a tutorial.".format(user))
        if scopes:
            missing = []
            for scope in scopes:
                if scope not in doc["key"]["permissions"]:
                    missing.append(scope)
            if missing:
                missing = ", ".join(missing)
                raise APIKeyError(
                    "{.mention}, your API key is missing the following "
                    "permissions to use this command: `{}`\nConsider adding "
                    "a new key with those permissions "
                    "checked".format(user, missing))
        return doc["key"]

    async def cache_dailies(self, *, tomorrow=False):
        if not tomorrow:
            try:
                await self.cache_endpoint("achievements")
            except Exception:
                pass
        try:
            ep = "achievements/daily"
            if tomorrow:
                ep += "/tomorrow"
            results = await self.call_api(ep)
            doc = {}
            for category, dailies in results.items():
                daily_list = []
                for daily in dailies:
                    if not daily["level"]["max"] == 80:
                        continue
                    daily_doc = await self.db.achievements.find_one(
                        {"_id": daily["id"]})
                    if not daily_doc:
                        continue
                    name = daily_doc["name"]
                    if category == "fractals":
                        if name.startswith(
                                "Daily Tier"
                        ) and not name.startswith("Daily Tier 4"):
                            continue
                    daily_list.append(name)
                daily_list.sort()
                if category == "pve":
                    daily_list.extend(self.get_lw_dailies(tomorrow=tomorrow))
                doc[category] = daily_list
            offset = 0
            if tomorrow:
                offset = 1
            doc["psna"] = [self.get_psna(offset_days=offset)]
            doc["psna_later"] = [self.get_psna(offset_days=1 + offset)]
            key = "cache.dailies"
            if tomorrow:
                key += "_tomorrow"
            await self.bot.database.set_cog_config(self, {key: doc})
        except Exception as e:
            self.log.exception("Exception caching dailies: ", exc_info=e)
        if not tomorrow:
            await self.cache_dailies(tomorrow=True)

    async def cache_raids(self):
        raids = []
        raids_index = await self.call_api("raids")
        for raid in raids_index:
            raids.append(await self.call_api("raids/" + raid))
        await self.bot.database.set_cog_config(self, {"cache.raids": raids})

    async def cache_pois(self):
        async def bulk_write(group):
            requests = []
            for item in group:
                item["_id"] = item.pop("id")
                requests.append(
                    ReplaceOne({"_id": item["_id"]}, item, upsert=True))
            try:
                await self.db.pois.bulk_write(requests)
            except BulkWriteError as e:
                self.log.exception("BWE while caching continents")

        continents = await self.call_api("continents/1/floors?ids=all")
        pois = []
        for continent in continents:
            for region in continent["regions"].values():
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
        config = await self.bot.database.get_cog_config(self)
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

        schema = datetime.datetime(2019, 12, 19)
        items = await self.call_api(endpoint, schema_version=schema)
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
                itemgroup = await self.call_api(f"{endpoint}?ids={ids}",
                                                schema_version=schema)
                await bulk_write(itemgroup)
                counter += 200
        else:
            itemgroup = await self.call_api("{}?ids=all".format(endpoint),
                                            schema_version=schema)
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
                     ["worlds", True], ["minis", True], ["pvp/amulets", True],
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
        await self.db.worlds.create_index("name")
        await self.cache_raids()
        await self.cache_pois()
        end = time.time()
        await self.bot.change_presence()
        self.bot.available = True
        print("Done")
        self.log.info("Database done! Time elapsed: {} seconds".format(end -
                                                                       start))

    async def itemname_to_id(self,
                             ctx,
                             item,
                             *,
                             flags=[],
                             filters={},
                             database="items",
                             group_duplicates=False,
                             prompt_user=False,
                             component_context=None,
                             limit=125,
                             hidden=False,
                             placeholder="Select the item you want..."
                             ):  # TODO cleanup this monstrosity
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
                    "ids": v,
                    "type": k[2]
                })
            return unique_list

        item_sanitized = re.escape(item)
        search = re.compile(item_sanitized + ".*", re.IGNORECASE)
        query = {"name": search, "flags": {"$nin": flags}, **filters}
        number = await self.db[database].count_documents(query)
        if not number:
            await ctx.send(
                "Your search gave me no results, sorry. Check for "
                "typos.\nAlways use singular forms, e.g. Legendary Insight")
            return None
        cursor = self.db[database].find(query)

        if number > limit:  # TODO multiple selections for 125 items.
            await ctx.send("Your search gave me {} item results. "
                           "Please be more specific".format(number))
            return None
        items = []
        async for item in cursor:
            items.append(item)
        items.sort(key=lambda i: i["name"])
        if group_duplicates:
            distinct_items = consolidate_duplicates(items)
        else:
            for item in items:
                item["ids"] = [item["_id"]]
            distinct_items = items

        if len(distinct_items) == 1:
            if not prompt_user:
                return distinct_items
            return distinct_items, None
        if not prompt_user:
            return distinct_items
        rows = []
        options = []
        for i, item in enumerate(
                sorted(distinct_items, key=lambda c: c["name"]), 1):
            if not i % limit:
                rows.append(options)
                options = []
            emoji = self.get_emoji(ctx, item["type"], return_obj=True)
            options.append(
                create_select_option(item["name"],
                                     i - 1,
                                     description=item["rarity"],
                                     emoji=emoji or None))
        rows.append(options)
        action_rows = []
        for row in rows:
            ph = placeholder
            if len(rows) > 1:
                first_letter = row[0]["label"][0]
                last_letter = row[-1]["label"][0]
                if first_letter != last_letter:
                    ph += f" [{first_letter}-{last_letter}]"
                else:
                    ph += f" [{first_letter}]"
            action_rows.append(
                create_actionrow(
                    create_select(row,
                                  min_values=1,
                                  max_values=1,
                                  placeholder=ph)))

        if len(rows) > 1:
            content = f"Due to Discord limitations, your selection had been split into several."
        else:
            content = "** **"
        if component_context:
            await component_context.edit_origin(content=content,
                                                components=action_rows)
        else:
            msg = await ctx.send(content,
                                 components=action_rows,
                                 hidden=hidden)

        def tell_off(answer):
            self.bot.loop.create_task(
                answer.send("Only the command owner may do that.",
                            hidden=True))

        try:
            while True:
                answer = await wait_for_component(self.bot,
                                                  components=action_rows,
                                                  timeout=120)
                if answer.author != ctx.author:
                    tell_off(answer)
                    continue
                index = int(answer.selected_options[0])
                return distinct_items[index], answer
        except asyncio.TimeoutError:
            if component_context:
                await component_context.edit_origin(content="Timed out.",
                                                    components=None)
            else:
                await msg.edit(content="Timed out.", components=None)
            return None, None
        # for item in items:
        #     if item["_id"] in choice["ids"]:
        #         if item["type"] == "UpgradeComponent":
        #             choice["is_upgrade"] = True

        # return choice

    async def selection_menu(self,
                             ctx,
                             cursor,
                             number,
                             *,
                             filter_callable=None):
        # TODO implement fields

        def check(m):
            return m.channel == ctx.channel and m.author == ctx.author

        if not number:
            await ctx.send(
                "Your search gave me no results, sorry. Check for "
                "typos.\nAlways use singular forms, e.g. Legendary Insight")
            return None
        if number > 25:
            await ctx.send("Your search gave me {} item results. "
                           "Please be more specific".format(number))
            return None
        items = []
        async for item in cursor:
            items.append(item)
        key = "name"
        if filter_callable:
            items = filter_callable(items)
        items.sort(key=lambda i: i[key])
        options = []
        if len(items) != 1:
            for i, item in enumerate(items):
                options.append(create_select_option(item[key], value=i))
            select = create_select(min_values=1,
                                   max_values=1,
                                   options=options,
                                   placeholder="Select the item you want")
            components = [create_actionrow(select)]
            msg = await ctx.send("** **", components=components)
            try:
                answer: ComponentContext = await self.bot.wait_for(
                    "component",
                    timeout=120,
                    check=lambda context: context.author == ctx.author and
                    context.origin_message.id == msg.id)
                choice = items[int(answer.selected_options[0])]
                await answer.defer(edit_origin=True)
                return (choice, answer)
            except asyncio.TimeoutError:
                await msg.edit(content="No response in time", components=None)
                return None
        else:
            choice = items[0]
        return choice

    async def get_historical_world_pop_data(self):
        # This might break in the future, but oh well
        url = "https://pop.apfelcreme.net/serverinfo.php?id={}"
        cursor = self.db.worlds.find({})
        async for world in cursor:
            try:
                world_id = world["_id"]
                async with self.session.get(url.format(world_id)) as r:
                    data = await r.json()
                    for entry in data:
                        pop = self.population_to_int(entry["population"])
                        if not entry["time_stamp"]:
                            continue
                        date = datetime.datetime.fromtimestamp(
                            entry["time_stamp"] / 1000)
                        doc = {
                            "population": pop,
                            "world_id": world_id,
                            "date": date
                        }
                        await self.db.worldpopulation.replace_one(
                            {
                                "world_id": world_id,
                                "date": date
                            },
                            doc,
                            upsert=True)
                        print("added " + world["name"] + ": " + str(pop))
            except Exception as e:
                print(f"Unable to get data for world: {world['name']}\n{e}")
