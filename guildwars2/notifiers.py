import asyncio
import datetime
import html
import re
import xml.etree.ElementTree as et

import discord
from bs4 import BeautifulSoup
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError


class NotiifiersMixin:
    @commands.group(case_insensitive=True)
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

    @commands.group(case_insensitive=True)
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

    @commands.group(case_insensitive=True)
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
            mention = doc["updates"].get("mention", "here")
            if mention == "none":
                suffix = ""
            else:
                suffix = (" **WARNING** Currently bot will "
                          "mention `@{}`. Use `{}updatenotifier "
                          "mention` to change that".format(
                              mention, ctx.prefix))
            msg = ("I will now automatically send update notifications to "
                   "{.mention}.".format(channel) + suffix)
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
                    mention = doc["updates"].get("mention", "here")
                    if mention == "none":
                        suffix = ""
                    else:
                        suffix = (" **WARNING** Currently bot will "
                                  "mention `@{}`. Use `{}updatenotifier "
                                  "mention` to change that".format(
                                      mention, ctx.prefix))
                    msg = (
                        "I will now automatically send update notifications "
                        "to {.mention}".format(channel) + suffix)
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

    @commands.cooldown(1, 5, BucketType.guild)
    @updatenotifier.command(name="mention", usage="<mention type>")
    async def updatenotifier_mention(self, ctx, mention_type):
        """Change the type of mention to be included with update notifier

        Possible values:
        none
        here
        everyone
        """
        valid_types = "none", "here", "everyone"
        mention_type = mention_type.lower()
        if mention_type not in valid_types:
            return await self.bot.send_cmd_help(ctx)
        guild = ctx.guild
        await self.bot.database.set_guild(
            guild, {"updates.mention": mention_type}, self)
        await ctx.send("Mention type set")

    @commands.group(case_insensitive=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def bossnotifier(self, ctx):
        """Sends the next two bosses every 15 minutes to a channel
        """
        if ctx.invoked_subcommand is None:
            return await self.bot.send_cmd_help(ctx)

    @commands.cooldown(1, 5, BucketType.guild)
    @bossnotifier.command(name="channel")
    async def bossnotifier_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel to send the bosses to"""
        guild = ctx.guild
        if not guild.me.permissions_in(channel).send_messages:
            return await ctx.send("I do not have permissions to send "
                                  "messages to {.mention}".format(channel))
        await self.bot.database.set_guild(
            guild, {"bossnotifs.channel": channel.id}, self)
        doc = await self.bot.database.get_guild(guild, self)
        enabled = doc["bossnotifs"].get("on", False)
        if enabled:
            msg = ("I will now send upcoming bosses to {.mention}."
                   "\nLast message will be automatically deleted.".format(
                       channel))
        else:
            msg = ("Channel set to {.mention}. In order to receive "
                   "upcoming bosses, you still need to enable it using "
                   "`bossnotifier toggle on`.".format(channel))
        await channel.send(msg)

    @commands.cooldown(1, 5, BucketType.guild)
    @bossnotifier.command(name="toggle")
    async def bossnotifier_toggle(self, ctx, on_off: bool):
        """Toggles posting upcoming bosses"""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {"bossnotifs.on": on_off},
                                          self)
        if on_off:
            doc = await self.bot.database.get_guild(guild, self)
            channel = doc["bossnotifs"].get("channel")
            if channel:
                channel = guild.get_channel(channel)
                if channel:
                    msg = ("I will now send upcoming bosses to {.mention}."
                           "\nLast message will be automatically deleted.".
                           format(channel))
            else:
                msg = ("Boss notifier toggled on. In order to receive "
                       "bosses, you still need to set a channel using "
                       "`bossnotifier channel <channel>`.".format(channel))
        else:
            msg = ("Boss notifier disabled")
        await ctx.send(msg)

    async def update_notification(self, new_build):
        def get_short_patchnotes(body, url):
            if len(body) < 1000:
                return body
            return body[:1000] + "... [Read more]({})".format(url)

        async def get_page(url):
            async with self.session.get(url + ".json") as r:
                return await r.json()

        def patchnotes_embed(embed, notes):
            notes = "\n".join(html.unescape(notes).splitlines())
            notes = re.sub('#{5} ', '**', notes)
            notes = re.sub('(\*{2}.*)', r'\1**', notes)
            notes = re.sub('\*{4}', '**', notes)
            headers = re.findall('#{4}.*', notes, re.MULTILINE)
            values = re.split('#{4}.*', notes)
            counter = 0
            if headers:
                for header in headers:
                    counter += 1
                    header = re.sub("#{4} ", "", header)
                    values[counter] = re.sub("\n\n", "\n", values[counter])
                    embed.add_field(name=header, value=values[counter])
            else:
                embed.description = notes
            return embed

        base_url = "https://en-forum.guildwars2.com"
        url_category = base_url + "/categories/game-release-notes"
        category = await get_page(url_category)
        category = category["Category"]
        last_discussion = category["LastDiscussionID"]
        url_topic = base_url + "/discussion/{}".format(last_discussion)
        patch_notes = ""
        title = "GW2 has just updated"
        try:  # Playing it safe in case forums die or something
            topic_result = await get_page(url_topic)
            topic = topic_result["Discussion"]
            last_comment = topic["LastCommentID"]
            if not last_comment:
                comment_url = url_topic
                body = topic["Body"]
            else:
                comment_url = url_topic + "#Comment_{}".format(last_comment)
                for comment in topic_result["Comments"]:
                    if comment["CommentID"] == last_comment:
                        body = comment["Body"]
                        break
                else:
                    raise Exception("Comment not found")
            patch_notes = get_short_patchnotes(body, comment_url)
            url_topic = comment_url
            title = topic["Name"]
        except Exception as e:
            self.log.exception(e)
        embed = discord.Embed(
            title="**{}**".format(title),
            url=url_topic,
            color=self.embed_color)
        if patch_notes:
            embed = patchnotes_embed(embed, patch_notes)
        embed.set_footer(text="Build: {}".format(new_build))
        text_version = ("@here Guild Wars 2 has just updated! "
                        "New build: {} Update notes: <{}>\n{}".format(
                            new_build, url_topic, patch_notes))
        return embed, text_version

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
                        embed.set_thumbnail(
                            url="https://wiki.guildwars2.com/images/"
                            "1/14/Daily_Achievement.png")
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
            doc = await self.bot.database.get_cog_config(self)
            build = doc["cache"]["build"]
            name = self.__class__.__name__
            embed_available = False
            try:
                embed, text = await self.update_notification(build)
                embed_available = True
            except:
                text = ("Guild Wars 2 has just updated! New build: {}".format(
                    build))
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
                    mention = guild.get("mention", "here")
                    if mention == "none":
                        mention = ""
                    else:
                        mention = "@{} ".format(mention)
                    channel = self.bot.get_channel(guild["channel"])
                    if (channel.permissions_for(channel.guild.me).embed_links
                            and embed_available):
                        message = mention + "Guild Wars 2 has just updated!"
                        await channel.send(message, embed=embed)
                    else:
                        await channel.send(text)
                    sent += 1
                except:
                    pass
            self.log.info("Update notifs: sent {}".format(sent))
        except Exception as e:
            self.log.exception(e)

    async def daily_checker(self):
        if await self.check_day():
            await asyncio.sleep(300)
            if not self.bot.available:
                await asyncio.sleep(360)
            await self.cache_dailies()
            await self.send_daily_notifs()

    async def news_checker(self):
        to_post = await self.check_news()
        if to_post:
            embeds = []
            for item in to_post:
                embeds.append(self.news_embed(item))
            await self.send_news(embeds)

    async def game_update_checker(self):
        if await self.check_build():
            await self.send_update_notifs()
            await self.rebuild_database()

    async def gem_tracker(self):
        name = self.__class__.__name__
        cost = await self.get_gem_price()
        cost_coins = self.gold_to_coins(None, cost)
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
                    await self.bot.database.set_user(user, {"gemtrack": None},
                                                     self)
            except:
                pass

    async def boss_notifier(self):
        name = self.__class__.__name__
        boss = self.get_upcoming_bosses(1)[0]
        await asyncio.sleep(boss["diff"].total_seconds() + 1)
        cursor = self.bot.database.get_guilds_cursor({
            "bossnotifs.on": True,
            "bossnotifs.channel": {
                "$ne": None
            }
        }, self)
        async for doc in cursor:
            try:
                doc = doc["cogs"][name]["bossnotifs"]
                channel = self.bot.get_channel(doc["channel"])
                timezone = await self.get_timezone(channel.guild)
                embed = self.schedule_embed(2, timezone=timezone)
                try:
                    message = await channel.send(embed=embed)
                except discord.Forbidden:
                    message = await channel.send("Need permission to "
                                                 "embed links in order "
                                                 "to send boss "
                                                 "notifs!")
                    continue
                await self.bot.database.set_guild(
                    channel.guild, {"bossnotifs.message": message.id}, self)
                old_message = doc.get("message")
                if old_message:
                    to_delete = await channel.get_message(old_message)
                    await to_delete.delete()
            except:
                pass

    async def world_population_checker(self):
        await self.send_population_notifs()
        await asyncio.sleep(300)
        await self.cache_endpoint("worlds", True)

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

    async def forced_account_names(self):
        cursor = self.bot.database.get_guilds_cursor(
            {
                "force_account_names": True
            }, self)
        async for doc in cursor:
            try:
                guild = self.bot.get_guild(doc["_id"])
                await self.force_guild_account_names(guild)
            except:
                pass
