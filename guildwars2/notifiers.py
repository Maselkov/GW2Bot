import asyncio
import datetime
import unicodedata
import xml.etree.ElementTree as et

import discord
from bs4 import BeautifulSoup
from discord.ext import tasks
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType
from discord_slash.utils.manage_components import (create_actionrow,
                                                   create_select,
                                                   create_select_option,
                                                   wait_for_component)

from .daily import DAILY_CATEGORIES
from .exceptions import APIError


class NotiifiersMixin:
    @cog_ext.cog_subcommand(
        base="notifier",
        name="daily",
        base_description="Notifier Commands",
        options=[{
            "name":
            "channel",
            "description":
            "The channel to post to. Leave blank to disable, required "
            "otherwise",
            "type":
            SlashCommandOptionType.CHANNEL,
            "required":
            False,
            "channel_types": [0]
        }, {
            "name": "pin_message",
            "description":
            "Toggle whether to automatically pin the daily message or not",
            "type": SlashCommandOptionType.BOOLEAN,
            "required": False,
        }, {
            "name":
            "behavior",
            "description":
            "Select additional behavior for deleting/editing the message. "
            "Leave blank for standard behavior.",
            "type":
            SlashCommandOptionType.STRING,
            "choices": [
                {
                    "value":
                    "autodelete",
                    "name":
                    "Delete the previous day's message. Causes an unread "
                    "notification."
                },
                {
                    "value":
                    "autoedit",
                    "name":
                    "Edit the previous day's message. No unread notification."
                },
            ],
            "required":
            False
        }])
    async def daily_notifier(self,
                             ctx,
                             *,
                             channel=None,
                             pin_message=False,
                             behavior=None):
        """Send daily achievements to a channel every day"""
        if not ctx.guild:
            return await ctx.send(
                "This command can only be used in servers at the time.",
                hidden=True)
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send("You need the `manage server` permission "
                                  "to use this command.")
        doc = await self.bot.database.get(ctx.guild, self)
        enabled = doc.get("daily", {}).get("on", False)
        if not enabled and not channel:
            return await ctx.send(
                "Daily notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument.",
                hidden=True)
        if enabled and not channel:
            await self.bot.database.set(ctx.guild, {"daily.on": False}, self)
            return await ctx.send("Daily notifier disabled.")
        if not ctx.guild.me.permissions_in(channel).send_messages:
            return await ctx.send(
                "I do not have permissions to send "
                f"messages to {channel.mention}",
                hidden=True)
        if not ctx.guild.me.permissions_in(channel).embed_links:
            return await ctx.send(
                "I do not have permissions to embed links in "
                f"{channel.mention}",
                hidden=True)
        options = []
        for category in DAILY_CATEGORIES:
            emoji = self.get_emoji(ctx, f"daily_{category}", return_obj=True)
            options.append(
                create_select_option(category["name"],
                                     category["value"],
                                     emoji=emoji or None))
        row = [
            create_actionrow(
                create_select(options,
                              placeholder="Select which categories "
                              "you want the bot to post",
                              min_values=1,
                              max_values=len(DAILY_CATEGORIES)))
        ]
        msg = await ctx.send("** **", components=row)
        while True:
            try:
                answer = await wait_for_component(self.bot,
                                                  components=row,
                                                  timeout=120)
                if answer.author != ctx.author:
                    self.tell_off(answer)
                    continue
                break
            except asyncio.TimeoutError:
                return await msg.edit(content="No response in time.",
                                      components=None)
        embed = await self.daily_embed(answer.selected_options, ctx=ctx)
        autodelete = False
        autoedit = False
        if behavior == "autodelete":
            autodelete = True
        if behavior == "autoedit":
            autoedit = True
        settings = {
            "daily.on": True,
            "daily.channel": channel.id,
            "daily.autopin": pin_message,
            "daily.autodelete": autodelete,
            "daily.autoedit": autoedit,
            "daily.categories": answer.selected_options
        }
        await self.bot.database.set(ctx.guild, settings, self)
        await answer.edit_origin(
            content=
            f"I will now send dailies to {channel.mention}. Here's an example "
            "notification:",
            embed=embed,
            components=None)

    @cog_ext.cog_subcommand(
        base="notifier",
        name="news",
        base_description="Notifier Commands",
        options=[{
            "name":
            "channel",
            "description":
            "The channel to post to. Leave blank to disable, required "
            "otherwise",
            "type":
            SlashCommandOptionType.CHANNEL,
            "required":
            False,
            "channel_types": [0]
        }])
    async def newsfeed(self, ctx, *, channel=None):
        """Automatically sends news from guildwars2.com to a specified channel"""
        if not ctx.guild:
            return await ctx.send(
                "This command can only be used in servers at the time.",
                hidden=True)
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send("You need the `manage server` permission "
                                  "to use this command.")
        doc = await self.bot.database.get(ctx.guild, self)
        enabled = doc.get("news", {}).get("on", False)
        if not enabled and not channel:
            return await ctx.send(
                "News notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument.",
                hidden=True)
        if enabled and not channel:
            await self.bot.database.set(ctx.guild, {"news.on": False}, self)
            return await ctx.send("News notifier disabled.")
        if not ctx.guild.me.permissions_in(channel).send_messages:
            return await ctx.send(
                "I do not have permissions to send "
                f"messages to {channel.mention}",
                hidden=True)
        if not ctx.guild.me.permissions_in(channel).embed_links:
            return await ctx.send(
                "I do not have permissions to embed links in "
                f"{channel.mention}",
                hidden=True)
        settings = {"news.on": True, "news.channel": channel.id}
        await self.bot.database.set(ctx.guild, settings, self)
        await ctx.send(f"I will now send news to {channel.mention}.")

    @cog_ext.cog_subcommand(
        base="notifier",
        name="update",
        base_description="Notifier Commands",
        options=[{
            "name":
            "channel",
            "description":
            "The channel to post to. Leave blank to disable, required "
            "otherwise",
            "type":
            SlashCommandOptionType.CHANNEL,
            "required":
            False,
            "channel_types": [0]
        }, {
            "name": "mention",
            "description":
            "The mention to ping when posting the notification. Can be a role, or everyone, or even a user.",
            "type": SlashCommandOptionType.MENTIONABLE,
            "required": False,
            "channel_types": [0]
        }])
    async def updatenotifier(self, ctx, *, channel=None, mention=None):
        """Send a notification whenever the game is updated"""
        if not ctx.guild:
            return await ctx.send(
                "This command can only be used in servers at the time.",
                hidden=True)
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send("You need the `manage server` permission "
                                  "to use this command.")
        doc = await self.bot.database.get(ctx.guild, self)
        enabled = doc.get("updates", {}).get("on", False)
        if not enabled and not channel:
            return await ctx.send(
                "Update notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument.",
                hidden=True)
        if enabled and not channel:
            await self.bot.database.set(ctx.guild, {"updates.on": False}, self)
            return await ctx.send("Update notifier disabled.")
        mention_string = ""
        if mention:
            mention = int(mention)
            if mention == ctx.guild.id:
                mention = "@everyone"
            elif role := ctx.guild.get_role(mention):
                mention_string = role.mention
            else:
                mention_string = ctx.guild.get_member(mention).mention

        settings = {
            "updates.on": True,
            "updates.channel": channel.id,
            "updates.mention": mention_string
        }
        await self.bot.database.set(ctx.guild, settings, self)
        await ctx.send(
            f"I will now send update notifications to {channel.mention}.")

    @cog_ext.cog_subcommand(
        base="notifier",
        name="bosses",
        base_description="Notifier Commands",
        options=[{
            "name":
            "channel",
            "description":
            "The channel to post to. Leave blank to disable, required "
            "otherwise",
            "type":
            SlashCommandOptionType.CHANNEL,
            "required":
            False,
            "channel_types": [0]
        }, {
            "name":
            "edit",
            "description":
            "Edit the previous message instead of deleting it. If not, posts "
            "a new message. Defaults to False",
            "type":
            SlashCommandOptionType.BOOLEAN,
            "required":
            False
        }])
    async def bossnotifier(self, ctx, *, channel=None, edit=False):
        """Send the next two bosses every 15 minutes to a channel"""
        key = "bossnotifs"
        if not ctx.guild:
            return await ctx.send(
                "This command can only be used in servers at the time.",
                hidden=True)
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send("You need the `manage server` permission "
                                  "to use this command.")
        doc = await self.bot.database.get(ctx.guild, self)
        enabled = doc.get(key, {}).get("on", False)
        if not enabled and not channel:
            return await ctx.send(
                "Boss notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument.",
                hidden=True)
        if enabled and not channel:
            await self.bot.database.set(ctx.guild, {f"{key}.on": False}, self)
            return await ctx.send("Boss notifier disabled.")
        settings = {
            f"{key}.on": True,
            f"{key}.channel": channel.id,
            f"{key}.edit": edit
        }
        await self.bot.database.set(ctx.guild, settings, self)
        await ctx.send(
            f"I will now send boss notifications to {channel.mention}.")

    async def update_notification(self, new_build):
        def get_short_patchnotes(body, url):
            if len(body) < 1000:
                return body
            return body[:1000] + "... [Read more]({})".format(url)

        async def get_page(url):
            async with self.session.get(url) as r:
                return BeautifulSoup(await r.text(), 'html.parser')

        base_url = "https://en-forum.guildwars2.com/"
        category = await get_page(base_url + "forum/6-game-update-notes/")

        patch_notes = discord.Embed.Empty
        title = "GW2 has just updated"
        url = discord.Embed.Empty
        try:  # Playing it safe in case forums die or something
            topic_url = category.find("span", {
                "class": "ipsType_break ipsContained"
            }).find("a")["href"].split("?")[0]

            topic = await get_page(topic_url)
            comment = topic.find_all("div",
                                     {"data-role": "commentContent"})[-1]
            comment_id = comment.parent.parent["data-commentid"]
            url = f"{topic_url}?do=findComment&comment={comment_id}"
            patch_notes = "\n".join(line
                                    for line in comment.get_text().split("\n")
                                    if line)
            patch_notes = get_short_patchnotes(patch_notes, url)
            title = topic.find("span", {
                "class": "ipsType_break ipsContained"
            }).get_text().strip()

        except Exception as e:
            self.log.exception(e)
        embed = discord.Embed(title=f"**{title}**",
                              url=url,
                              color=self.embed_color,
                              description=patch_notes)
        embed.set_footer(text="Build: {}".format(new_build))
        text_version = ("@here Guild Wars 2 has just updated! "
                        "New build: {} Update notes: <{}>\n{}".format(
                            new_build, url, patch_notes))
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
                except Exception:
                    pass
        last_news = [x.find("title").text for x in feed.findall("item")]
        await self.bot.database.set_cog_config(self, {"cache.news": last_news})
        return to_post

    def news_embed(self, item):
        soup = BeautifulSoup(item["description"], 'html.parser')
        description = "[Click here]({0})\n{1}".format(item["link"],
                                                      soup.get_text())
        data = discord.Embed(title=unicodedata.normalize(
            "NFKD", item["title"]),
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
        cursor = self.bot.database.iter("guilds", {
            "daily.on": True,
            "daily.channel": {
                "$ne": None
            }
        },
                                        self,
                                        subdocs=["daily"])
        daily_doc = await self.bot.database.get_cog_config(self)

        async def notify_guild(doc):
            categories = doc.get("categories")
            if not categories:
                categories = [
                    "psna", "psna_later", "pve", "pvp", "wvw", "fractals",
                    "strikes"
                ]
            if "psna" in categories and not "psna_later" in categories:
                categories.insert(categories.index("psna") + 1, "psna_later")
            channel = self.bot.get_channel(doc["channel"])
            embed = await self.daily_embed(categories,
                                           doc=daily_doc,
                                           ctx=channel)

            edit = doc.get("autoedit", False)
            autodelete = doc.get("autodelete", False)
            old_message = None
            if autodelete or edit:
                try:
                    old_message_id = doc.get("message")
                    if old_message_id:
                        old_message = await channel.fetch_message(
                            old_message_id)
                except discord.HTTPException:
                    pass
            edited = False
            try:
                embed.set_thumbnail(url="https://wiki.guildwars2.com/images/"
                                    "1/14/Daily_Achievement.png")
                if old_message and edit:
                    try:
                        await old_message.edit(embed=embed)
                        edited = True
                    except discord.HTTPException:
                        pass
                if not edited:
                    message = await channel.send(embed=embed)
            except discord.Forbidden:
                message = await channel.send("Need permission to "
                                             "embed links in order "
                                             "to send daily "
                                             "notifs!")
            if autodelete and not edited:
                try:
                    await old_message.delete()
                except discord.HTTPException:
                    pass
            if not edited:
                await self.bot.database.set_guild(
                    channel.guild, {"daily.message": message.id}, self)
            autopin = doc.get("autopin", False)
            if autopin:
                message = old_message
                if edited:
                    if message.pinned:
                        return
                try:
                    await message.pin()
                    try:
                        async for m in channel.history(after=message, limit=3):
                            if (m.type == discord.MessageType.pins_add
                                    and m.author == self.bot.user):
                                await m.delete()
                                break
                    except Exception:
                        pass
                    if not edited:
                        old_message = doc.get("message")
                        if old_message:
                            to_unpin = await channel.fetch_message(old_message)
                            await to_unpin.unpin()
                except Exception:
                    pass

        async for doc in cursor:
            try:
                asyncio.create_task(notify_guild(doc))
            except Exception:
                pass

    async def send_news(self, embeds):
        cursor = self.bot.database.iter(
            "guilds",
            {
                "news.on": True,
                "news.channel": {
                    "$ne": None
                }
            },
            self,
            subdocs=["news"],
        )
        to_filter = ["the arenanet streaming schedule", "community showcase"]
        filtered = [
            embed.title for embed in embeds
            if any(f in embed.title.lower() for f in to_filter)
        ]
        async for doc in cursor:
            try:
                channel = self.bot.get_channel(doc["channel"])
                filter_on = doc.get("filter", True)
                for embed in embeds:
                    if filter_on:
                        if embed.title in filtered:
                            continue
                    await channel.send(embed=embed)
            except Exception as e:
                self.log.exception(e)

    async def send_update_notifs(self):
        try:
            doc = await self.bot.database.get_cog_config(self)
            build = doc["cache"]["build"]
            name = self.__class__.__name__
            embed_available = False
            try:
                embed, text = await self.update_notification(build)
                embed_available = True
            except Exception:
                text = ("Guild Wars 2 has just updated! New build: {}".format(
                    build))
            cursor = self.bot.database.get_guilds_cursor(
                {
                    "updates.on": True,
                    "updates.channel": {
                        "$ne": None
                    }
                }, self)
            sent = 0
            async for doc in cursor:
                try:
                    guild = doc["cogs"][name]["updates"]
                    mention = guild.get("mention", "")
                    if mention == "everyone" or mention == "here":  # Legacy, too lazy to update atm, TODO
                        mention = "@" + mention
                    if mention == "none":
                        mention = ""
                    channel = self.bot.get_channel(guild["channel"])
                    if (channel.permissions_for(channel.guild.me).embed_links
                            and embed_available):
                        message = mention + " Guild Wars 2 has just updated!"
                        await channel.send(message, embed=embed)
                    else:
                        await channel.send(text)
                    sent += 1
                except Exception:
                    pass
            self.log.info("Update notifs: sent {}".format(sent))
        except Exception as e:
            self.log.exception(e)

    @tasks.loop(minutes=3)
    async def daily_checker(self):
        if await self.check_day():
            await asyncio.sleep(300)
            if not self.bot.available:
                await asyncio.sleep(360)
            await self.cache_dailies()
            await self.send_daily_notifs()

    @tasks.loop(minutes=3)
    async def news_checker(self):
        to_post = await self.check_news()
        if to_post:
            embeds = []
            for item in to_post:
                embeds.append(self.news_embed(item))
            await self.send_news(embeds)

    @tasks.loop(minutes=1)
    async def game_update_checker(self):
        if await self.check_build():
            await self.send_update_notifs()
            await self.rebuild_database()

    @tasks.loop(minutes=5)
    async def gem_tracker(self):
        cost = await self.get_gem_price()
        cost_coins = self.gold_to_coins(None, cost)
        cursor = self.bot.database.iter("users", {"gemtrack": {
            "$ne": None
        }}, self)
        async for doc in cursor:
            try:
                if cost < doc["gemtrack"]:
                    user = doc["_obj"]
                    user_price = self.gold_to_coins(None, doc["gemtrack"])
                    msg = ("Hey, {.mention}! You asked to be notified "
                           "when 400 gems were cheaper than {}. Guess "
                           "what? They're now only "
                           "{}!".format(user, user_price, cost_coins))
                    await user.send(msg)
                    await self.bot.database.set(user, {"gemtrack": None}, self)
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    @tasks.loop(minutes=5)
    async def boss_notifier(self):
        name = self.__class__.__name__
        boss = self.get_upcoming_bosses(1)[0]
        await asyncio.sleep(boss["diff"].total_seconds() + 1)
        cursor = self.bot.database.get_guilds_cursor(
            {
                "bossnotifs.on": True,
                "bossnotifs.channel": {
                    "$ne": None
                }
            }, self)
        async for doc in cursor:
            try:
                doc = doc["cogs"][name]["bossnotifs"]
                edit = doc.get("edit", False)
                channel = self.bot.get_channel(doc["channel"])
                embed = self.schedule_embed(2)
                edited = False
                try:
                    if edit:
                        old_message = await channel.fetch_message(
                            doc["message"])
                        if old_message:
                            try:
                                await old_message.edit(embed=embed)
                                edited = True
                                continue
                            except discord.HTTPException:
                                pass
                    message = await channel.send(embed=embed)
                except discord.Forbidden:
                    message = await channel.send("Need permission to "
                                                 "embed links in order "
                                                 "to send boss "
                                                 "notifs!")
                    continue
                if not edited:
                    await self.bot.database.set(
                        channel.guild, {"bossnotifs.message": message.id},
                        self)
                    old_message_id = doc.get("message")
                    if old_message_id:
                        to_delete = await channel.fetch_message(old_message_id)
                        await to_delete.delete()
            except asyncio.CancelledError:
                self.log.error("Big dead")
                return
            except Exception:
                pass

    @tasks.loop(minutes=15)
    async def world_population_checker(self):
        await self.send_population_notifs()
        await asyncio.sleep(300)
        await self.cache_endpoint("worlds", True)
        cursor = self.db.worlds.find({})
        date = datetime.datetime.utcnow()
        async for world in cursor:
            doc = await self.db.worldpopulation.find_one(
                {"world_id": world["_id"]}, sort=[("date", -1)])
            current_pop = self.population_to_int(world["population"])
            if not doc or current_pop != doc["population"]:
                await self.db.worldpopulation.insert_one({
                    "population":
                    current_pop,
                    "world_id":
                    world["_id"],
                    "date":
                    date
                })

    async def send_population_notifs(self):
        async for world in self.db.worlds.find({"population": {
                "$ne": "Full"
        }}):
            world_name = world["name"]
            wid = world["_id"]
            msg = (
                "{} is no longer full! [populationtrack]".format(world_name))
            cursor = self.bot.database.get_users_cursor({"poptrack": wid},
                                                        self)
            async for doc in cursor:
                try:
                    user = await self.bot.fetch_user(doc["_id"])
                    await self.bot.database.set_user(user, {"poptrack": wid},
                                                     self,
                                                     operator="$pull")
                    await user.send(msg)
                except asyncio.CancelledError:
                    return
                except Exception:
                    pass

    @tasks.loop(minutes=5)
    async def forced_account_names(self):
        cursor = self.bot.database.get_guilds_cursor(
            {"force_account_names": True}, self)
        async for doc in cursor:
            try:
                guild = self.bot.get_guild(doc["_id"])
                await self.force_guild_account_names(guild)
            except asyncio.CancelledError:
                return
            except Exception:
                pass
