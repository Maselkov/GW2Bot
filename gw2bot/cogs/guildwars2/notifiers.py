import asyncio
import datetime
import json
import unicodedata
import xml.etree.ElementTree as et

import aiohttp

import discord
from bs4 import BeautifulSoup
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import tasks

from ..commerce import gem_price
from . import update_notes
from ..daily import DAILY_CATEGORIES
from .exceptions import APIError
from gw2bot.utils.markdown import html_to_markdown


class DailyCategoriesDropdown(discord.ui.Select):
    def __init__(self, interaction, cog, behavior, pin_message, channel):
        options = []
        self.cog = cog
        self.behavior = behavior
        self.pin_message = pin_message
        self.channel = channel
        self.selected_values = []
        for category in DAILY_CATEGORIES:
            emoji = cog.get_emoji(
                interaction, f"daily {category['value']}", return_obj=True
            )
            options.append(
                discord.SelectOption(
                    label=category["name"], value=category["value"], emoji=emoji or None
                )
            )
        super().__init__(
            placeholder="Select which categories you want the bot to post",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_options = self.values
        await interaction.response.defer(ephemeral=True)
        categories = self.values
        # The Daily cog builds the example until /notifier moves out of this
        # cog too (a command group can't span cogs)
        daily = self.cog.bot.get_cog("Daily")
        try:
            embed = await daily.daily_embed(categories, interaction=interaction) if daily else None
        except ValueError:
            embed = None
        autodelete = False
        autoedit = False
        if self.behavior == "autodelete":
            autodelete = True
        if self.behavior == "autoedit":
            autoedit = True
        settings = {
            "daily.on": True,
            "daily.channel": self.channel.id,
            "daily.autopin": self.pin_message,
            "daily.autodelete": autodelete,
            "daily.autoedit": autoedit,
            "daily.categories": categories,
        }
        await self.cog.bot.data.guilds.update(interaction.guild.id, settings)
        content = f"I will now send dailies to {self.channel.mention}."
        if embed:
            content += " Here's an example notification:"
        await interaction.edit_original_response(
            content=content, embed=embed, view=None
        )
        self.view.stop()


class NotiifiersMixin:
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    class NotifierGroup(
        app_commands.Group,
        name="notifier",
        description="Commands for setting various notifiers for your server",
    ):
        pass

    notifier_group = NotifierGroup()
    reminder_group = app_commands.Group(
        name="reminder", description="Commands for setting various personal reminders."
    )

    @notifier_group.command(name="daily")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        enabled="Enable or disable Daily Notifier. If "
        "enabling, channel argument must be set",
        channel="The channel to post to.",
        pin_message="Toggle whether to " "automatically pin the daily message or not.",
        behavior="Select additional behavior for "
        "deleting/editing the message. Leave blank for standard behavior.",
    )
    @app_commands.choices(
        behavior=[
            Choice(
                name="Delete the previous day's message and post a new message. "
                "Causes an unread notification",
                value="autodelete",
            ),
            Choice(
                name="Edit the previous day's message. No unread notification.",
                value="autoedit",
            ),
        ]
    )
    async def daily_notifier(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        channel: discord.TextChannel = None,
        pin_message: bool = False,
        behavior: str = None,
    ):
        """Send daily achievements to a channel every day"""
        doc = await self.bot.data.guilds.get(interaction.guild.id)
        already_enabled = doc.get("daily", {}).get("on", False)
        if enabled and not channel:
            await interaction.response.send_message(
                "You must specify a channel to post to. using the 'Channel' parameter",
                ephemeral=True,
            )
            return
        if not enabled and not already_enabled:
            return await interaction.response.send_message(
                "Daily notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument.",
                ephemeral=True,
            )
        if not enabled:
            await self.bot.data.guilds.update(interaction.guild.id, {"daily.on": False})
            return await interaction.response.send_message("Daily notifier disabled.")
        if not channel.permissions_for(interaction.guild.me).send_messages:
            return await interaction.response.send_message(
                "I do not have permissions to send " f"messages to {channel.mention}",
                ephemeral=True,
            )
        if not channel.permissions_for(interaction.guild.me).embed_links:
            return await interaction.response.send_message(
                "I do not have permissions to embed links in " f"{channel.mention}",
                ephemeral=True,
            )
        view = discord.ui.View(timeout=60)
        view.add_item(
            DailyCategoriesDropdown(interaction, self, behavior, pin_message, channel)
        )
        await interaction.response.send_message("** **", view=view, ephemeral=True)
        if await view.wait():
            return await interaction.followup.edit_message(
                content="No response in time.", view=None
            )

    @notifier_group.command(name="news")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        enabled="Enable or disable game news notifier. If "
        "enabling, channel argument must be set",
        channel="The channel to post to.",
        mention="The role to ping when posting the notification.",
    )
    async def newsfeed(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        channel: discord.TextChannel = None,
        mention: discord.Role = None,
    ):
        """Automatically sends news from guildwars2.com to a specified channel"""
        if enabled and not channel:
            return await interaction.response.send_message(
                "You must specify a channel.", ephemeral=True
            )
        doc = await self.bot.data.guilds.get(interaction.guild.id)
        already_enabled = doc.get("news", {}).get("on", False)
        if not already_enabled and not channel:
            return await interaction.response.send_message(
                "News notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument.",
                ephemeral=True,
            )
        if already_enabled and not channel:
            await self.bot.data.guilds.update(interaction.guild.id, {"news.on": False})
            return await interaction.response.send_message(
                "News notifier disabled.", ephemeral=True
            )
        if not channel.permissions_for(interaction.guild.me).send_messages:
            return await interaction.response.send_message(
                "I do not have permissions to send " f"messages to {channel.mention}",
                ephemeral=True,
            )
        if not channel.permissions_for(interaction.guild.me).embed_links:
            return await interaction.response.send_message(
                "I do not have permissions to embed links in " f"{channel.mention}",
                ephemeral=True,
            )
        role_id = mention.id if mention else None
        settings = {"news.on": True, "news.channel": channel.id, "news.role": role_id}
        await self.bot.data.guilds.update(interaction.guild.id, settings)
        await interaction.response.send_message(
            f"I will now send news to {channel.mention}."
        )

    @notifier_group.command(name="update")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(
        enabled="Enable or disable game update notifier. If "
        "enabling, channel argument must be set",
        channel="The channel to post to.",
        mention="The role to ping when posting the notification.",
    )
    async def updatenotifier(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        channel: discord.TextChannel = None,
        mention: discord.Role = None,
    ):
        """Send a notification whenever the game is updated"""
        if enabled and not channel:
            return await interaction.response.send_message(
                "You must specify a channel with the 'channel' optional argument.",
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in servers at the time.", ephemeral=True
            )
        doc = await self.bot.data.guilds.get(interaction.guild.id)
        already_enabled = doc.get("updates", {}).get("on", False)
        if not already_enabled and not enabled:
            return await interaction.response.send_message(
                "Update notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument.",
                ephemeral=True,
            )
        if not enabled:
            await self.bot.data.guilds.update(interaction.guild.id, {"updates.on": False})
            return await interaction.response.send_message("Update notifier disabled.")
        mention_string = ""
        if mention:
            mention_string = mention.mention
        settings = {
            "updates.on": True,
            "updates.channel": channel.id,
            "updates.mention": mention_string,
        }
        await self.bot.data.guilds.update(interaction.guild.id, settings)
        await interaction.response.send_message(
            f"I will now send update notifications to {channel.mention}."
        )

    @notifier_group.command(name="bosses")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(
        enabled="Enable or disable boss notifier. "
        "If enabling, channel argument must be set",
        channel="The channel to post to.",
        behavior="Select behavior for posting/editing the message. Defaults to "
        "posting a new message",
    )
    @app_commands.choices(
        behavior=[
            Choice(
                name="Delete the previous day's message. "
                "Causes an unread notification.",
                value="delete",
            ),
            Choice(
                name="Edit the previous day's message. No unread "
                "notification, but bad for active channels",
                value="edit",
            ),
        ]
    )
    async def bossnotifier(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        channel: discord.TextChannel = None,
        behavior: str = "delete",
    ):
        """Send the next two bosses every 15 minutes to a channel"""
        await interaction.response.defer(ephemeral=True)
        edit = behavior == "edit"
        if enabled and not channel:
            return await interaction.followup.send("You must specify a channel.")
        key = "bossnotifs"
        doc = await self.bot.data.guilds.get(interaction.guild.id)
        enabled = doc.get(key, {}).get("on", False)
        if not enabled and not channel:
            return await interaction.followup.send(
                "Boss notifier is aleady disabled. If "
                "you were trying to enable it, make sure to fill out "
                "the `channel` argument."
            )
        if enabled and not channel:
            await self.bot.data.guilds.update(interaction.guild.id, {f"{key}.on": False})
            return await interaction.followup.send("Boss notifier disabled.")
        settings = {
            f"{key}.on": True,
            f"{key}.channel": channel.id,
            f"{key}.edit": edit,
        }
        await self.bot.data.guilds.update(interaction.guild.id, settings)
        await interaction.followup.send(
            f"I will now send boss notifications to {channel.mention}."
        )

    async def event_name_autocomplete(self, interaction: discord.Interaction, current):
        if not current:
            return []
        current = current.lower()
        names = set()
        timers = self.gamedata["event_timers"]
        for category in timers:
            if category == "bosses":
                subtypes = "normal", "hardcore"
                for subtype in subtypes:
                    for boss in timers[category][subtype]:
                        name = boss["name"]
                        if current in name.lower():
                            names.add(Choice(name=name, value=name))
            else:
                for subcategory in timers[category]:
                    map_name = subcategory["name"]
                    for event in subcategory["phases"]:
                        if event["name"]:
                            name = f"{map_name} - {event['name']}"
                            if current in name.lower():
                                names.add(Choice(name=name, value=event["name"]))
        return sorted(list(names)[:25], key=lambda c: c.name)

    @reminder_group.command(name="event")
    @app_commands.describe(
        event_name="Event name. Examples: Shadow Behemoth. Gerent Preparation",
        minutes_before_event="The number of minutes before "
        "the event that you'll be notified at",
    )
    @app_commands.autocomplete(event_name=event_name_autocomplete)
    async def reminder_event(
        self,
        interaction: discord.Interaction,
        event_name: str,
        minutes_before_event: int = 5,
    ):
        """Make the bot automatically notify you before an event starts"""
        if minutes_before_event < 0:
            return await interaction.response.send_message(
                "That's not how time works!", ephemeral=True
            )
        if minutes_before_event > 60:
            return await interaction.response.send_message(
                "Time can't be greater than one hour", ephemeral=True
            )
        event_name = event_name.lower()
        reminder = {}
        for boss in self.boss_schedule:
            if boss["name"].lower() == event_name:
                reminder["type"] = "boss"
                reminder["name"] = boss["name"]
        if not reminder:
            # Every map event group the timers have (all but world bosses)
            groups = [g for g in self.gamedata["event_timers"] if g != "bosses"]
            for group in groups:
                maps = self.gamedata["event_timers"][group]
                for location in maps:
                    for phase in location["phases"]:
                        if not phase["name"]:
                            continue
                        if phase["name"].lower() == event_name:
                            reminder["type"] = "phase"
                            reminder["name"] = phase["name"]
                            reminder["group"] = group
                            reminder["map_name"] = location["name"]
        if not reminder:
            return await interaction.response.send_message(
                "No event found matching that name", ephemeral=True
            )
        reminder["time"] = minutes_before_event * 60
        await self.bot.data.users.update(
            interaction.user.id, {"event_reminders": reminder}, op="push"
        )
        await interaction.response.send_message(
            "Reminder set succesfully", ephemeral=True
        )

    async def update_notification(self, new_build):
        """[(embed, text, minor)] for update-notes posts not announced yet.

        Posts come from the forum topic page. When that can't be read (the
        forum answers some clients with a Cloudflare challenge), the RSS
        feed's copy of the first post is used instead.
        """
        updates = self.bot.data.gw2.updates

        def build_embed(title, url, data):
            if len(data) >= 1000:
                data = data[:1000] + " ..."
            e = discord.Embed(title=title, color=discord.Color.dark_red())
            e.url = url
            e.add_field(name="Update Notes", value=data)
            e.set_footer(text="Build: {}".format(new_build))
            return e

        async def fetch(url):
            """(status, body) for a GET."""
            timeout = aiohttp.ClientTimeout(total=30)
            async with self.session.get(url, timeout=timeout) as response:
                return response.status, await response.text()

        status, feed = await fetch(update_notes.FEED_URL)
        if status != 200:
            self.log.warning("Update notes: feed returned %s", status)
            return None
        latest = update_notes.parse_feed(feed)
        if not latest:
            return None
        title, link, first_post, published = latest

        doc = await updates.find_one({"title": title})
        if not doc:
            await updates.insert_one({"title": title, "count": 0})
        sent = doc["count"] if doc else 0
        if sent == 0 and update_notes.too_old_to_announce(published):
            # Old thread whose first post was never announced: skip it, but
            # still send later posts (hotfixes)
            sent = 1

        status, page = await fetch(link)
        posts = update_notes.parse_topic_posts(page) if status == 200 else []
        blocked = not posts
        if blocked != getattr(self, "update_notes_blocked", False):
            # Logged on change only; this runs every minute
            if blocked:
                self.log.warning(
                    "Update notes: can't read forum posts (HTTP %s), using the RSS feed's first post", status
                )
            else:
                self.log.info("Update notes: forum posts readable again")
            self.update_notes_blocked = blocked
        if blocked and first_post:
            posts = [first_post]

        to_send = update_notes.notes_to_send(sent, posts)
        if not to_send:
            return None
        await updates.update_one({"title": title}, {"$set": {"title": title, "count": len(posts)}})
        text_version = "Guild Wars 2 has just updated!"
        return [
            (build_embed(title, link, html_to_markdown(post)), text_version, minor)
            for post, minor in to_send
        ]

    async def check_news(self):
        doc = await self.bot.data.config.get()
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
                        to_post.append(
                            {
                                "link": item.find("link").text,
                                "title": item.find("title").text,
                                "description": item.find("description").text.split(
                                    "</p>", 1
                                )[0],
                            }
                        )
                except Exception:
                    pass
        last_news = [x.find("title").text for x in feed.findall("item")]
        await self.bot.data.config.update({"cache.news": last_news})
        return to_post

    def news_embed(self, item):
        soup = BeautifulSoup(item["description"], "html.parser")
        description = "[Click here]({0})\n{1}".format(item["link"], soup.get_text())
        data = discord.Embed(
            title=unicodedata.normalize("NFKD", item["title"]),
            description=description,
            color=0xC12D2B,
        )
        return data

    async def game_build_changed(self):
        doc = await self.bot.data.config.get()
        if not doc:
            return False
        current_build = doc["cache"]["build"]
        url = "http://assetcdn.101.arenanetworks.com/latest/101"
        async with self.session.get(url) as r:
            some_weird_numbers: str = await r.text()
        some_weird_numbers = some_weird_numbers.split()
        build = some_weird_numbers[0]
        if current_build != build:
            await self.bot.data.config.update({"cache.build": build})
            return True
        else:
            return False

    async def send_news(self, embeds):
        cursor = self.guild_subdocs("news", {"news.on": True, "news.channel": {"$ne": None}})
        to_filter = ["the arenanet streaming schedule", "community showcase"]
        filtered = [
            embed.title
            for embed in embeds
            if any(f in embed.title.lower() for f in to_filter)
        ]
        async for doc in cursor:
            try:
                if not doc["_obj"]:
                    continue
                channel = self.bot.get_channel(doc["channel"])
                if not channel:
                    continue
                filter_on = doc.get("filter", True)
                role_id = doc.get("role")
                content = None
                if role_id:
                    role = channel.guild.get_role(role_id)
                    if role:
                        content = role.mention
                for embed in embeds:
                    if filter_on:
                        if embed.title in filtered:
                            continue
                    await channel.send(content, embed=embed)
            except discord.Forbidden:
                await self.bot.data.guilds.update(doc["_id"], {"news.on": False})
            except Exception as e:
                self.log.exception(e)

    async def send_update_notifs(self):
        doc = await self.bot.data.config.get()
        build = doc["cache"]["build"]
        embed_available = False
        try:
            result = await self.update_notification(build)
            if not result:
                return
            for embed, text, minor in result:
                embed_available = True
                cursor = self.guild_subdocs("updates", {"updates.on": True, "updates.channel": {"$ne": None}})
                sent = 0
                async for doc in cursor:
                    try:
                        if not doc["on"]:
                            continue
                        channel = self.bot.get_channel(doc["channel"])
                        if not channel:
                            continue
                        if not minor:
                            mention = doc.get("mention", "")
                            if (
                                mention == "everyone" or mention == "here"
                            ):  # Legacy, too lazy to update atm, TODO
                                mention = "@" + mention
                            if mention == "none":
                                mention = ""
                        else:
                            mention = ""
                        if (
                            channel.permissions_for(channel.guild.me).embed_links
                            and embed_available
                        ):
                            message = mention + " Guild Wars 2 has just updated!"
                            await channel.send(message, embed=embed)
                        else:
                            await channel.send(text)
                        sent += 1
                    except Exception as e:
                        self.log.exception(e)
                self.log.info("Update notifs: sent {}".format(sent))
        except Exception as e:
            self.log.exception(e)

    @tasks.loop(minutes=3)
    async def news_checker(self):
        try:
            to_post = await self.check_news()
        except Exception:
            # E.g. an error page instead of the feed. An escaping exception
            # would stop the loop for good
            self.log.exception("Couldn't check the news")
            return
        if to_post:
            embeds = []
            for item in to_post:
                embeds.append(self.news_embed(item))
            await self.send_news(embeds)

    @news_checker.before_loop
    async def before_news_checker(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def game_update_checker(self):
        try:
            if await self.game_build_changed():
                await self.rebuild_database()
            await self.send_update_notifs()
        except Exception:
            # An escaping exception would stop the loop for good
            self.log.exception("Couldn't check for game updates")

    @game_update_checker.before_loop
    async def before_update_checker(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def gem_tracker(self):
        try:
            cost = await gem_price(self.api)
        except APIError as e:
            # An escaping exception would stop the loop for good
            self.log.warning("Couldn't check the gem price: %s", e)
            return
        cost_coins = self.gold_to_coins(None, cost)
        async for doc in self.bot.data.users.find({"gemtrack": {"$ne": None}}):
            try:
                if cost < doc["gemtrack"]:
                    user = self.bot.get_user(doc["_id"])
                    user_price = self.gold_to_coins(None, doc["gemtrack"])
                    msg = (
                        "Hey, {.mention}! You asked to be notified "
                        "when 400 gems were cheaper than {}. Guess "
                        "what? They're now only "
                        "{}!".format(user, user_price, cost_coins)
                    )
                    await user.send(msg)
                    await self.bot.data.users.update(user.id, {"gemtrack": None})
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    @gem_tracker.before_loop
    async def before_gem_tracker(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def boss_notifier(self):
        boss = self.get_upcoming_bosses(1)[0]
        await asyncio.sleep(boss["diff"].total_seconds() + 1)
        cursor = self.bot.data.guilds.find({"bossnotifs.on": True, "bossnotifs.channel": {"$ne": None}})
        async for doc in cursor:
            try:
                doc = doc["bossnotifs"]
                edit = doc.get("edit", False)
                channel = self.bot.get_channel(doc["channel"])
                embed = self.schedule_embed(2)
                old_message_id = doc.get("message")
                edited = False
                try:
                    if edit and old_message_id:
                        old_message = await channel.fetch_message(old_message_id)
                        if old_message:
                            try:
                                await old_message.edit(embed=embed)
                                edited = True
                                continue
                            except discord.HTTPException:
                                pass
                    message = await channel.send(embed=embed)
                except discord.Forbidden:
                    message = await channel.send(
                        "Need permission to "
                        "embed links in order "
                        "to send boss "
                        "notifs!"
                    )
                    continue
                if not edited:
                    await self.bot.data.guilds.update(channel.guild.id, {"bossnotifs.message": message.id})
                    old_message_id = doc.get("message")
                    if old_message_id:
                        to_delete = await channel.fetch_message(old_message_id)
                        await to_delete.delete()
            except asyncio.CancelledError:
                return
            except Exception:
                pass
            await asyncio.sleep(0.1)

    @boss_notifier.before_loop
    async def before_boss_notifier(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def forced_account_names(self):
        cursor = self.bot.data.guilds.find({"force_account_names": True})
        async for doc in cursor:
            try:
                guild = self.bot.get_guild(doc["_id"])
                await self.force_guild_account_names(guild)
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    @forced_account_names.before_loop
    async def before_forced_account_names(self):
        await self.bot.wait_until_ready()
