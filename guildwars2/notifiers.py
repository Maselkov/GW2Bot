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
            try:
                endpoint = "achievements/daily"
                results = await self.call_api(endpoint)
            except APIError as e:
                return await self.error_handler(ctx, e)
            example = await self.display_all_dailies(results, True)
            msg = ("I will now send dailies to {.mention}. "
                   "Example:\n```markdown\n{}```".format(channel, example))
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
                try:
                    endpoint = "achievements/daily"
                    results = await self.call_api(endpoint)
                except APIError as e:
                    return await self.error_handler(ctx, e)
                channel = guild.get_channel(channel)
                if channel:
                    example = await self.display_all_dailies(results, True)
                    msg = ("I will now send dailies to {.mention}. "
                           "Example:\n```markdown\n{}```".format(
                               channel, example))
            else:
                msg = ("Daily notifier toggled on. In order to reeceive "
                       "dailies, you still need to set a channel using "
                       "`dailynotifier channel <channel>`.".format(channel))
        else:
            msg = ("Daily notifier disabled")
        await ctx.send(msg)

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
                msg = ("Newsfeed toggled on. In order to reeceive "
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
            else:
                msg = ("Update notifier toggled on. In order to reeceive "
                       "update notifs, you still need to set a channel using "
                       "`updatenotifier channel <channel>`.".format(channel))
        else:
            msg = ("Update notifier disabled")
        await ctx.send(msg)

    async def get_patchnotes(self):
        url = "https://forum-en.guildwars2.com/forum/info/updates"
        async with self.session.get(url) as r:
            results = await r.text()
        soup = BeautifulSoup(results, 'html.parser')
        post = soup.find(class_="arenanet topic")
        return "https://forum-en.guildwars2.com" + post.find("a")["href"]

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
        description = "[Click here]({0})\n{1}".format(item["link"],
                                                      item["description"])
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
        day = doc["cache"]["day"]
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
            channels = []
            name = self.__class__.__name__
            cursor = self.bot.database.get_guilds_cursor({
                "daily.on": True,
                "daily.channel": {
                    "$ne": None
                }
            }, self)
            async for doc in cursor:
                try:
                    guild = doc["cogs"][name]["daily"]
                    channels.append(guild["channel"])
                except:
                    pass
            try:
                endpoint = "achievements/daily"
                results = await self.call_api(endpoint)
            except APIError as e:
                self.log.exception(e)
                return
            message = await self.display_all_dailies(results, True)
            message = "```markdown\n" + message + "```\nHave a nice day!"
            for chanid in channels:
                try:
                    await self.bot.get_channel(chanid).send(message)
                except:
                    pass
        except Exception as e:
            self.log.exception(e)
            return

    async def send_news(self, embeds):
        try:
            channels = []
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
                    channels.append(guild["channel"])
                except:
                    pass
            for chanid in channels:
                try:
                    for embed in embeds:
                        await self.bot.get_channel(chanid).send(embed=embed)
                except:
                    pass
        except Exception as e:
            self.log.exception(e)
            return

    async def send_update_notifs(self):
        try:
            channels = []
            name = self.__class__.__name__
            cursor = self.bot.database.get_guilds_cursor({
                "updates.on": True,
                "updates.channel": {
                    "$ne": None
                }
            }, self)
            async for doc in cursor:
                try:
                    guild = doc["cogs"][name]["updates"]
                    channels.append(guild["channel"])
                except:
                    pass
            try:
                link = await self.get_patchnotes()
                patchnotes = "\nUpdate notes: " + link
                doc = await self.bot.database.get_cog_config(self)
                build = doc["cache"]["build"]
            except:
                patchnotes = ""
            message = ("@here Guild Wars 2 has just updated! New build: "
                       "`{0}`{1}".format(build, patchnotes))
            for chanid in channels:
                try:
                    await self.bot.get_channel(chanid).send(message)
                except:
                    pass
        except Exception as e:
            self.log.exception(e)

    async def daily_checker(self):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                if await self.check_day():
                    await asyncio.sleep(300)
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
