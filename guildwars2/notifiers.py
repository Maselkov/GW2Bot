import asyncio
import datetime
import xml.etree.ElementTree as et

import discord
from bs4 import BeautifulSoup
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError


class NotiifiersMixin:
    @commands.group()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def dailynotifier(self, ctx):
        """Sends a list of dailies on server reset to specificed channel.
        First, specify a channel using $daily notifier channel <channel>
        Make sure it's toggle on using $daily notifier toggle on
        """
        if ctx.invoked_subcommand is None:
            return await self.bot.send_cmd_help(ctx)

    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name="channel")
    async def daily_notifier_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel to send the dailies on server reset to"""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permissions to send "
                                  "messages to {.mention}".format(channel))
        await self.bot.database.set_guild(guild, {"daily.channel": channel.id},
                                          self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc["daily"].get("on", False)
        if enabled:
            msg = ("I will now send dailies to {.mention}. "
                   "".format(channel))
        else:
            msg = ("Channel set to {.mention}. In order to receive "
                   "dailies, you still need to enable it using "
                   "`dailynotifier toggle on`.".format(channel))
        await channel.send(msg)

    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name="toggle")
    async def daily_notifier_toggle(self, ctx, on_off: bool):
        """Toggles posting dailies at server reset"""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {"daily.on": on_off}, self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc["daily"].get("channel")
            if channel:
                channel = guild.get_channel(channel)
                if channel:
                    msg = ("I will now send dailies to {.mention}. "
                           "".format(channel))
            else:
                msg = ("Daily notifier toggled on. In order to reeceive "
                       "dailies, you still need to set a channel using "
                       "`dailynotifier channel <channel>`.".format(channel))
        else:
            msg = ("Daily notifier disabled")
        await ctx.send(msg)

    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name="autodelete")
    async def daily_notifier_autodelete(self, ctx, on_off: bool):
        """Toggles automatically deleting last day's dailies"""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {"daily.autodelete": on_off},
                                          self)
        await ctx.send("Autodeletion for daily notifs enabled")

    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name="categories")
    async def daily_notifier_categories(self, ctx, *categories):
        """Set daily notifier to only display specific categories

        Separate multiple categories with space, possible values:
        all
        psna
        psna_later
        pve
        pvp
        wvw
        fractals

        psna_later is psna, 8 hours later
        PSNA changes 8 hours after dailies change.

        Example: $dailynotifier categories psna psna_later pve fractals
        """
        if not categories:
            await self.bot.send_cmd_help(ctx)
            return
        guild = ctx.guild
        possible_values = [
            "all", "psna", "psna_later", "pve", "pvp", "wvw", "fractals"
        ]
        categories = [x.lower() for x in categories]
        if len(categories) > 6:
            await self.bot.send_cmd_help(ctx)
            return
        for category in categories:
            if category not in possible_values:
                await self.bot.send_cmd_help(ctx)
                return
            if categories.count(category) > 1:
                await self.bot.send_cmd_help(ctx)
                return
            if category == "all":
                categories = [
                    "psna", "psna_later", "pve", "pvp", "wvw", "fractals"
                ]
                break
        embed = await self.daily_embed(categories)
        await self.bot.database.set_guild(
            guild, {"daily.categories": categories}, self)
        await ctx.send(
            "Your categories have been saved. Here's an example of "
            "your daily notifs:",
            embed=embed)

    @commands.cooldown(1, 5, BucketType.guild)
    @dailynotifier.command(name="autopin")
    async def daily_notifier_autopin(self, ctx, on_off: bool):
        """Set daily notifier to automatically pin the message for the day

        If enabled, will try to unpin last day's message as well
        """
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {"daily.autopin": on_off},
                                          self)
        await ctx.send("Autopinning for daily notifs enabled")

    @commands.group()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def newsfeed(self, ctx):
        """Automatically sends new from guildwars2.com to specified channel"""
        if ctx.invoked_subcommand is None:
            return await self.bot.send_cmd_help(ctx)

    @newsfeed.command(name="channel")
    async def newsfeed_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel to send the news to"""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permissions to send "
                                  "messages to {.mention}".format(channel))
        await self.bot.database.set_guild(guild, {"news.channel": channel.id},
                                          self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc["news"].get("on", False)
        if enabled:
            msg = ("I will now automatically send news to "
                   "{.mention}.".format(channel))
        else:
            msg = ("Channel set to {.mention}. In order to receive "
                   "news, you still need to enable it using "
                   "`newsfeed toggle on`.".format(channel))
        await channel.send(msg)

    @newsfeed.command(name="toggle")
    async def newsfeed_toggle(self, ctx, on_off: bool):
        """Toggles posting news"""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {"news.on": on_off}, self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc["news"].get("channel")
            if channel:
                channel = guild.get_channel(channel)
                if channel:  # Channel can be none now
                    msg = (
                        "I will now send news to {.mention}.".format(channel))
            else:
                msg = ("Newsfeed toggled on. In order to receive "
                       "news, you still need to set a channel using "
                       "`newsfeed channel <channel>`.".format(channel))
        else:
            msg = ("Newsfeed disabled")
        await ctx.send(msg)

    @commands.group()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def updatenotifier(self, ctx):
        """Sends a notification whenever GW2 is updated"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @updatenotifier.command(name="channel")
    async def update_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel to send the update announcement"""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permissions to send "
                                  "messages to {.mention}".format(channel))
        await self.bot.database.set_guild(
            guild, {"updates.channel": channel.id}, self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc["updates"].get("on", False)
        if enabled:
            msg = (
                "I will now automatically send update notifications to "
                "{.mention}. **WARNING** these notifications include `@here` "
                "mention. Take away bot's permissions to mention everyone "
                "if you don't want it.".format(channel))
        else:
            msg = ("Channel set to {.mention}. In order to receive "
                   "update notifications, you still need to enable it using "
                   "`updatenotifier toggle on`.".format(channel))
        await channel.send(msg)

    @updatenotifier.command(name="toggle")
    async def update_toggle(self, ctx, on_off: bool):
        """Toggles sending game update notifications"""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {"updates.on": on_off}, self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc["updates"].get("channel")
            if channel:
                channel = guild.get_channel(channel)
                if channel:  # Channel can be none now
                    msg = (
                        "I will now automatically send update notifications "
                        "to {.mention}. **WARNING** these notifications "
                        "include `@here` mention. Take away bot's permissions "
                        "to mention everyone if you don't "
                        "want it.".format(channel))
                else:  # TODO change it, ugly
                    msg = (
                        "Update notifier toggled on. In order to reeceive "
                        "update notifs, you still need to set a channel using "
                        "`updatenotifier channel <channel>`.")
            else:
                msg = ("Update notifier toggled on. In order to reeceive "
                       "update notifs, you still need to set a channel using "
                       "`updatenotifier channel <channel>`.")
        else:
            msg = ("Update notifier disabled")
        await ctx.send(msg)

    async def get_patchnotes(self):
        base_url = "https://en-forum.guildwars2.com"
        url_updates = base_url + "/categories/game-release-notes"
        async with self.session.get(url_updates) as r:
            results = await r.text()
        soup = BeautifulSoup(results, 'html.parser')
        post = soup.find(class_="Title")
        link = post["href"]
        try:
            async with self.session.get(link) as r:
                results = await r.text()
            soup = BeautifulSoup(results, 'html.parser')
            new_link = soup.find_all(class_="Permalink")[-1].get('href')
            if new_link != link:
                link = base_url + new_link
        except:
            pass
        return "<{}>".format(link)

    async def check_news(self):
        doc = await self.bot.database.get_cog_config(self)
        if not doc:
            return []
        last_news = doc["cache"]["news"]
        url = "https://www.guildwars2.com/en/feed/"
        async with self.session.get(url) as r:
            feed = et.fromstring(await r.text())[0]
        to_post = []
        if last_news:
            for item in feed.findall("item"):
                try:
                    if item.find("title").text not in last_news:
                        to_post.append({
                            "link":
                            item.find("link").text,
                            "title":
                            item.find("title").text,
                            "description":
                            item.find("description").text.split("</p>", 1)[0]
                        })
                except:
                    pass
        last_news = [x.find("title").text for x in feed.findall("item")]
        await self.bot.database.set_cog_config(self, {"cache.news": last_news})
        return to_post

    def news_embed(self, item):
        soup = BeautifulSoup(item["description"], 'html.parser')
        description = "[Click here]({0})\n{1}".format(item["link"],
                                                      soup.get_text())
        data = discord.Embed(
            title="{0}".format(item["title"]),
            description=description,
            color=0xc12d2b)
        return data

    async def check_day(self):
        current = datetime.datetime.utcnow().weekday()
        doc = await self.bot.database.get_cog_config(self)
        if not doc:
            return False
        cache = doc["cache"]
        day = cache.get("day")
        dailies = cache.get("dailies")
        if not dailies:
            await self.cache_dailies()
        if day != current:
            await self.bot.database.set_cog_config(self,
                                                   {"cache.day": current})
            return True
        else:
            return False

    async def check_build(self):
        doc = await self.bot.database.get_cog_config(self)
        if not doc:
            return False
        current_build = doc["cache"]["build"]
        endpoint = "build"
        try:
            results = await self.call_api(endpoint)
        except APIError:
            return False
        build = results["id"]
        if not current_build == build:
            await self.bot.database.set_cog_config(self,
                                                   {"cache.build": build})
            return True
        else:
            return False

    async def send_daily_notifs(self):
        try:
            name = self.__class__.__name__
            cursor = self.bot.database.get_guilds_cursor({
                "daily.on": True,
                "daily.channel": {
                    "$ne": None
                }
            }, self)
            daily_doc = await self.bot.database.get_cog_config(self)
            sent = 0
            deleted = 0
            forbidden = 0
            pinned = 0
            async for doc in cursor:
                try:
                    guild = doc["cogs"][name]["daily"]
                    categories = guild.get("categories")
                    if not categories:
                        categories = [
                            "psna", "psna_later", "pve", "pvp", "wvw",
                            "fractals"
                        ]
                    embed = await self.daily_embed(categories, doc=daily_doc)
                    channel = self.bot.get_channel(guild["channel"])
                    try:
                        message = await channel.send(embed=embed)
                        sent += 1
                    except discord.Forbidden:
                        forbidden += 1
                        message = await channel.send("Need permission to "
                                                     "embed links in order "
                                                     "to send daily "
                                                     "notifs!")
                    await self.bot.database.set_guild(
                        channel.guild, {"daily.message": message.id}, self)
                    autodelete = guild.get("autodelete", False)
                    if autodelete:
                        try:
                            old_message = guild.get("message")
                            if old_message:
                                to_delete = await channel.get_message(
                                    old_message)
                                await to_delete.delete()
                                deleted += 1
                        except:
                            pass
                    autopin = guild.get("autopin", False)
                    if autopin:
                        try:
                            await message.pin()
                            pinned += 1
                            try:
                                async for m in channel.history(
                                        after=message, limit=3):
                                    if (m.type == discord.MessageType.pins_add
                                            and m.author == self.bot.user):
                                        await m.delete()
                                        break
                            except:
                                pass
                            old_message = guild.get("message")
                            if old_message:
                                to_unpin = await channel.get_message(
                                    old_message)
                                await to_unpin.unpin()
                        except:
                            pass

                except:
                    pass
            self.log.info(
                "Daily notifs: sent {}, deleted {}, forbidden {}, pinned {}".
                format(sent, deleted, forbidden, pinned))
        except Exception as e:
            self.log.exception(e)
            return

    async def send_news(self, embeds):
        try:
            name = self.__class__.__name__
            cursor = self.bot.database.get_guilds_cursor({
                "news.on": True,
                "news.channel": {
                    "$ne": None
                }
            }, self)
            async for doc in cursor:
                try:
                    guild = doc["cogs"][name]["news"]
                    channel = self.bot.get_channel(guild["channel"])
                    for embed in embeds:
                        await channel.send(embed=embed)
                except:
                    pass
        except Exception as e:
            self.log.exception("Exception sending daily notifs: ", exc_info=e)

    async def send_update_notifs(self):
        try:
            name = self.__class__.__name__
            try:
                link = await self.get_patchnotes()
                patchnotes = "\nUpdate notes: " + link
                doc = await self.bot.database.get_cog_config(self)
                build = doc["cache"]["build"]
            except:
                patchnotes = ""
            message = ("@here Guild Wars 2 has just updated! New build: "
                       "`{0}`{1}".format(build, patchnotes))
            cursor = self.bot.database.get_guilds_cursor({
                "updates.on": True,
                "updates.channel": {
                    "$ne": None
                }
            }, self)
            sent = 0
            async for doc in cursor:
                try:
                    guild = doc["cogs"][name]["updates"]
                    await self.bot.get_channel(guild["channel"]).send(message)
                    sent += 1
                except:
                    pass
            self.log.info("Update notifs: sent {}".format(sent))
        except Exception as e:
            self.log.exception(e)

    async def daily_checker(self):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                if await self.check_day():
                    await asyncio.sleep(300)
                    if not self.bot.available:
                        await asyncio.sleep(360)
                    await self.cache_dailies()
                    await self.send_daily_notifs()
                await asyncio.sleep(60)
            except Exception as e:
                self.log.exception(e)
                await asyncio.sleep(60)
                continue

    async def news_checker(self):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                to_post = await self.check_news()
                if to_post:
                    embeds = []
                    for item in to_post:
                        embeds.append(self.news_embed(item))
                    await self.send_news(embeds)
                await asyncio.sleep(300)
            except Exception as e:
                self.log.exception(e)
                await asyncio.sleep(300)
                continue

    async def game_update_checker(self):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                if await self.check_build():
                    await self.send_update_notifs()
                    await self.rebuild_database()
                await asyncio.sleep(60)
            except Exception as e:
                self.log.exception(e)
                await asyncio.sleep(60)
                continue

    async def gem_tracker(self):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                name = self.__class__.__name__
                cost = await self.get_gem_price()
                cost_coins = self.gold_to_coins(cost)
                cursor = self.bot.database.get_users_cursor({
                    "gemtrack": {
                        "$ne": None
                    }
                }, self)
                async for doc in cursor:
                    try:
                        user_price = doc["cogs"][name]["gemtrack"]
                        if cost < user_price:
                            user = await self.bot.get_user_info(doc["_id"])
                            user_price = self.gold_to_coins(user_price)
                            msg = ("Hey, {.mention}! You asked to be notified "
                                   "when 400 gems were cheaper than {}. Guess "
                                   "what? They're now only "
                                   "{}!".format(user, user_price, cost_coins))
                            await user.send(msg)
                            await self.bot.database.set_user(
                                user, {"gemtrack": None}, self)
                    except:
                        pass
                await asyncio.sleep(150)
            except Exception as e:
                self.log.exception("Exception during gemtracker: ", exc_info=e)
                await asyncio.sleep(150)

    async def world_population_checker(self):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                await self.send_population_notifs()
                await asyncio.sleep(300)
                await self.cache_endpoint("worlds", True)
            except Exception as e:
                self.log.exception("Exception during popnotifs: ", exc_info=e)
                await asyncio.sleep(300)
                continue

    async def send_population_notifs(self):
        async for world in self.db.worlds.find({
                "population": {
                    "$ne": "Full"
                }
        }):
            world_name = world["name"]
            wid = world["_id"]
            msg = (
                "{} is no longer full! [populationtrack]".format(world_name))
            cursor = self.bot.database.get_users_cursor({
                "poptrack": wid
            }, self)
            async for doc in cursor:
                try:
                    user = await self.bot.get_user_info(doc["_id"])
                    await self.bot.database.set_user(
                        user, {"poptrack": wid}, self, operator="$pull")
                    await user.send(msg)
                except:
                    pass
