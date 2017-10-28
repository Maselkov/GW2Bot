import asyncio
import re
import time

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from pymongo.errors import BulkWriteError

from .exceptions import APIKeyError


class DatabaseMixin:
    @commands.command()
    @commands.cooldown(1, 5, BucketType.user)
    async def skillinfo(self, ctx, *, skill):
        """Information about a given skill"""
        user = ctx.author
        skill_sanitized = re.escape(skill)
        search = re.compile(skill_sanitized + ".*", re.IGNORECASE)
        cursor = self.db.skills.find({"name": search})
        number = await cursor.count()
        if not number:
            await ctx.send(
                "Your search gave me no results, sorry. Check for typos.")
            return
        if number > 20:
            await ctx.send(
                "Your search gave me {} results. Please be more specific".
                format(number))
            return
        items = []
        msg = "Which one of these interests you? Type it's number```"
        async for item in cursor:
            items.append(item)
        if number != 1:
            for c, m in enumerate(items):
                msg += "\n{}: {}".format(c, m["name"])
            msg += "```"
            message = await ctx.send(msg)

            def check(m):
                return m.channel == ctx.channel and m.author == user

            try:
                answer = await self.bot.wait_for(
                    "message", timeout=120, check=check)
            except asyncio.TimeoutError:
                message.edit(content="No response in time")
                return None
            try:
                num = int(answer.content)
                choice = items[num]
            except:
                await message.edit(content="That's not a number in the list")
                return None
            try:
                await answer.delete()
            except:
                pass
        else:
            message = await ctx.send("Searching far and wide...")
            choice = items[0]
        data = await self.skill_embed(choice)
        try:
            await message.edit(content=None, embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    async def skill_embed(self, skill):
        # Very inconsistent endpoint, playing it safe
        description = None
        if "description" in skill:
            description = skill["description"]
        url = "https://wiki.guildwars2.com/wiki/" + skill["name"].replace(
            ' ', '_')
        async with self.session.head(url) as r:
            if not r.status == 200:
                url = None
        data = discord.Embed(
            title=skill["name"], description=description, url=url)
        if "icon" in skill:
            data.set_thumbnail(url=skill["icon"])
        if "professions" in skill:
            if skill["professions"]:
                professions = skill["professions"]
                if len(professions) != 1:
                    data.add_field(
                        name="Professions", value=", ".join(professions))
                elif len(professions) == 9:
                    data.add_field(name="Professions", value="All")
                else:
                    data.add_field(
                        name="Profession", value=", ".join(professions))
        if "facts" in skill:
            for fact in skill["facts"]:
                try:
                    if fact["type"] == "Recharge":
                        data.add_field(name="Cooldown", value=fact["value"])
                    if fact["type"] == "Distance" or fact["type"] == "Number":
                        data.add_field(name=fact["text"], value=fact["value"])
                    if fact["type"] == "ComboField":
                        data.add_field(
                            name=fact["text"], value=fact["field_type"])
                except:
                    pass
        return data

    @commands.group()
    @commands.is_owner()
    async def database(self, ctx):
        """Commands related to DB management"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
            return

    @database.command(name="create")
    async def db_create(self, ctx):
        """Create a new database
        """
        await self.rebuild_database()

    @database.command(name="statistics")
    async def db_stats(self, ctx):
        """Some statistics
        """
        cursor = self.bot.database.get_users_cursor({
            "key": {
                "$ne": None
            }
        }, self)
        result = await cursor.count()
        await ctx.send("{} registered users".format(result))
        cursor_updates = self.bot.database.get_guilds_cursor({
            "updates.on": True
        })
        cursor_daily = self.bot.database.get_guilds_cursor({"daily.on": True})
        cursor_news = self.bot.database.get_guilds_cursor({"news.on": True})
        result_updates = await cursor_updates.count()
        result_daily = await cursor_daily.count()
        result_news = await cursor_news.count()
        await ctx.send("{} guilds for update notifs\n{} guilds for daily "
                       "notifs\n{} guilds for news "
                       "feed".format(result_updates, result_daily,
                                     result_news))

    async def get_title(self, title_id):
        try:
            results = await self.db.titles.find_one({"_id": title_id})
            title = results["name"]
        except:
            return ""
        return title

    async def get_world_name(self, wid):
        try:
            doc = await self.db.worlds.find_one({"_id": wid})
            name = doc["name"]
        except:
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
                    "{.mention}, missing the following scopes to use this "
                    "command: `{}`".format(user, missing))
        return doc["key"]

    async def cache_dailies(self):
        try:
            results = await self.call_api("achievements/daily")
            await self.cache_endpoint("achievements")
        except:
            return
        try:
            doc = {}
            for category, dailies in results.items():
                daily_list = []
                for daily in dailies:
                    if not daily["level"]["max"] == 80:
                        continue
                    daily_doc = await self.db.achievements.find_one({
                        "_id":
                        daily["id"]
                    })
                    name = daily_doc["name"]
                    if category == "fractals":
                        if name.startswith(
                                "Daily Tier"
                        ) and not name.startswith("Daily Tier 4"):
                            continue
                    daily_list.append(name)
                doc[category] = sorted(daily_list)
            doc["psna"] = [self.get_psna()]
            doc["psna_later"] = [self.get_psna(offset_days=1)]
            await self.bot.database.set_cog_config(self,
                                                   {"cache.dailies": doc})
        except Exception as e:
            self.log.exception("Exception caching dailies: ", exc_info=e)

    async def cache_raids(self):
        raids = []
        raids_index = await self.call_api("raids")
        for raid in raids_index:
            raids.append(await self.call_api("raids/" + raid))
        await self.bot.database.set_cog_config(self, {"cache.raids": raids})

    async def get_raids(self):
        config = await self.bot.database.get_cog_config(self)
        return config["cache"].get("raids")

    async def cache_endpoint(self, endpoint, all=False):
        await self.db[endpoint].drop()
        try:
            items = await self.call_api(endpoint)
        except Exception as e:
            self.log.warn(e)
        if not all:
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
                    "{}?ids={}".format(endpoint, ids))
                counter += 200
                for item in itemgroup:
                    item["_id"] = item.pop("id")
                try:
                    await self.db[endpoint].insert_many(itemgroup)
                except BulkWriteError as e:
                    self.log.exception(
                        "BWE while caching {}".format(endpoint), exc_info=e)
        else:
            itemgroup = await self.call_api("{}?ids=all".format(endpoint))
            for item in itemgroup:
                item["_id"] = item.pop("id")
            await self.db[endpoint].insert_many(itemgroup)

    async def rebuild_database(self):
        start = time.time()
        self.bot.available = False
        await self.bot.change_presence(
            game=discord.Game(name="Rebuilding API cache"),
            status=discord.Status.dnd)
        endpoints = [["items"], ["achievements"], ["itemstats", True], [
            "titles", True
        ], ["recipes"], ["skins"], ["currencies", True], ["skills", True],
                     ["specializations", True], ["traits",
                                                 True], ["worlds", True]]
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
        end = time.time()
        self.bot.available = True
        print("Done")
        self.log.info(
            "Database done! Time elapsed: {} seconds".format(end - start))

    async def itemname_to_id(self, ctx, item, user, *, flags=[], filters={}):
        def check(m):
            return m.channel == ctx.channel and m.author == user

        item_sanitized = re.escape(item)
        search = re.compile(item_sanitized + ".*", re.IGNORECASE)
        cursor = self.db.items.find({"name": search,
                                     "flags": {"$nin": flags},
                                     **filters})
        number = await cursor.count()
        if not number:
            await ctx.send(
                "Your search gave me no results, sorry. Check for "
                "typos.\nAlways use singular forms, e.g. Legendary Insight")
            return None
        if number > 20:
            await ctx.send("Your search gave me {} item results. Please be "
                           "more specific".format(number))
            return None
        items = []
        async for item in cursor:
            items.append(item)
        items.sort(key=lambda i: i["name"])
        longest = len(max([item["name"] for item in items], key=len))
        msg = [
            "Which one of these interests you? Simply type it's number "
            "into the chat now:```ml", "INDEX    NAME {}RARITY".format(
                " " * (longest)), "-----|------{}|-------".format(
                    "-" * (longest))
        ]
        if number != 1:
            for c, m in enumerate(items, 1):
                msg.append("  {} {}| {} {}| {}".format(c, " " * (
                    2 - len(str(c))), m["name"].upper(), " " * (
                        4 + longest - len(m["name"])), m["rarity"]))
            msg.append("```")
            message = await ctx.send("\n".join(msg))
            try:
                answer = await self.bot.wait_for(
                    "message", timeout=120, check=check)
            except asyncio.TimeoutError:
                message.edit(content="No response in time")
                return None
            try:
                num = int(answer.content) - 1
                choice = items[num]
            except:
                await message.edit(content="That's not a number in the list")
                return None
            try:
                await message.delete()
                await answer.delete()
            except:
                pass
        else:
            choice = items[0]
        return choice
