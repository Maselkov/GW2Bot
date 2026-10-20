"""Dailies: /daily, the dailies cache, and the daily notifier."""
import asyncio
import calendar
import datetime
import logging
import re

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import tasks

from gw2bot.utils.chat import en_space, tab

from ..gw2api.errors import APIError
from .base import GW2Cog

DAILY_CATEGORIES = [
    {
        "value": "psna",
        "name": "PSNA - Pact Supply Network Agent"
    },
    {
        "value": "fractals",
        "name": "Fractals"
    },
    {
        "value": "raids",
        "name": "Raid Bounties"
    },
    {
        "value": "lw",
        "name": "Living World Seasons 3 & 4"
    },
]
# Categories servers saved before the Wizard's Vault replaced daily
# achievements. Strikes are raid encounters now, and the Living World dailies
# used to be listed under PvE.
LEGACY_CATEGORIES = {"strikes": "raids", "pve": "lw"}
# Achievement categories that list the day's rotation in `achievements` and
# the next day's in `tomorrow`
ACHIEVEMENT_CATEGORIES = {
    "fractals": 88,
    "raids": 475,
    "lws3": 238,
    "lws4": 243,
}
# First schema with the `tomorrow` list
CATEGORY_SCHEMA = "2022-03-23T19:00:00.000Z"
PSNA_RESET = datetime.timedelta(hours=8)


def normalize_categories(categories):
    """Saved categories in display order, legacy ones mapped or dropped."""
    known = [cat["value"] for cat in DAILY_CATEGORIES]
    wanted = {LEGACY_CATEGORIES.get(cat, cat) for cat in categories or []}
    return [cat for cat in known if cat in wanted] or known


def daily_rotation(categories, names):
    """{"today": {key: [names]}, "tomorrow": {...}} for ACHIEVEMENT_CATEGORIES.

    categories: /v2/achievements/categories response (CATEGORY_SCHEMA).
    names: {achievement id: name}.
    """
    by_id = {category["id"]: category for category in categories}
    rotation = {"today": {}, "tomorrow": {}}
    for key, category_id in ACHIEVEMENT_CATEGORIES.items():
        category = by_id.get(category_id, {})
        for day, field in (("today", "achievements"), ("tomorrow", "tomorrow")):
            day_names = [
                names[entry["id"]] for entry in category.get(field) or []
                if entry["id"] in names
            ]
            if key == "fractals":
                # Only the top tier, like the old daily list
                day_names = [
                    name for name in day_names if name.startswith(
                        ("Daily Tier 4 ", "Daily Recommended Fractal"))
                ]
            rotation[day][key] = sorted(day_names)
    return rotation


class Daily(GW2Cog):

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)

    async def cog_load(self):
        self.refresh_dailies.start()
        self.send_daily_notifs.start()

    async def cog_unload(self):
        self.refresh_dailies.cancel()
        self.send_daily_notifs.cancel()

    @app_commands.command()
    @app_commands.describe(category="Daily type",
                           tomorrow="Show tomorrow's dailies instead")
    @app_commands.choices(category=[
        Choice(**cat) for cat in [{
            "name": "All",
            "value": "all"
        }] + DAILY_CATEGORIES
    ])
    async def daily(self,
                    interaction: discord.Interaction,
                    category: str,
                    tomorrow: bool = False):
        """Show today's daily achievements"""
        await interaction.response.defer()
        tomorrow = bool(tomorrow)
        if category == "all":
            category = [cat["value"] for cat in DAILY_CATEGORIES]
        else:
            category = [category]
        try:
            embed = await self.daily_embed(category,
                                           interaction=interaction,
                                           tomorrow=tomorrow)
        except ValueError:
            return await interaction.followup.send(
                "Dailies are currently unavailable. Try again in a bit",
                ephemeral=True)
        await interaction.followup.send(embed=embed)

    def get_year_day(self, tomorrow=True):
        date = datetime.datetime.now(datetime.timezone.utc).date()
        if tomorrow:
            date += datetime.timedelta(days=1)
        day = (date - date.replace(month=1, day=1)).days
        if day >= 59 and not calendar.isleap(date.year):
            day += 1
        return day

    async def daily_embed(self,
                          categories,
                          *,
                          doc=None,
                          interaction=None,
                          tomorrow=False):
        if not doc:
            doc = await self.bot.data.config.get()
        if interaction:
            color = await self.get_embed_color(interaction)
        else:
            color = self.embed_color
        embed = discord.Embed(title="Dailies", color=color)
        if tomorrow:
            embed.title += " tomorrow"
        key = "dailies" if not tomorrow else "dailies_tomorrow"
        dailies = doc["cache"].get(key)
        if not dailies or "raids" not in dailies:
            # Not cached yet, or still in the format from before the
            # Wizard's Vault
            raise ValueError
        categories = normalize_categories(categories)
        for category in categories:
            if category == "psna":
                self.add_psna_fields(embed, interaction, tomorrow=tomorrow)
            elif category == "fractals":
                fractals = self.get_fractals(dailies["fractals"],
                                             interaction,
                                             tomorrow=tomorrow)
                if fractals[0]:
                    embed.add_field(name="> Daily Fractals",
                                    value="\n".join(fractals[0]))
                embed.add_field(name="> CM Instabilities", value=fractals[2])
                if fractals[1]:
                    embed.add_field(
                        name="> Recommended Fractals",
                        value="\n".join(fractals[1]),
                        inline=False,
                    )
            elif category == "raids":
                emoji = self.get_emoji(interaction, "daily strike")
                lines = [
                    emoji + name.removeprefix("Raid Bounty: ")
                    for name in dailies["raids"]
                ]
                if lines:
                    embed.add_field(name="RAID BOUNTIES",
                                    value="\n".join(lines),
                                    inline=False)
            elif category == "lw":
                for season in "3", "4":
                    emoji = self.get_emoji(interaction, f"daily lws{season}")
                    lines = [
                        emoji + name.removeprefix("Daily ")
                        for name in dailies[f"lws{season}"]
                    ]
                    if lines:
                        embed.add_field(
                            name=f"LIVING WORLD SEASON {season}",
                            value="\n".join(lines),
                            inline=False)
        if "fractals" in categories:
            embed.set_footer(
                text=self.bot.user.name +
                " | Instabilities shown only apply to the highest scale",
                icon_url=self.bot.user.display_avatar.url,
            )
        else:
            embed.set_footer(text=self.bot.user.name,
                             icon_url=self.bot.user.display_avatar.url)
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        return embed

    def add_psna_fields(self, embed, ctx, *, tomorrow=False):
        """The agents at the start of the day and after their next reset."""
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now
        if tomorrow:
            start = (now + datetime.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        next_reset = day + PSNA_RESET
        if next_reset <= start:
            next_reset += datetime.timedelta(days=1)
        emoji = self.get_emoji(ctx, "daily psna")
        embed.add_field(name=emoji + "PSNA",
                        value=self.get_psna(start),
                        inline=False)
        embed.add_field(name=f"{emoji}PSNA <t:{int(next_reset.timestamp())}:R>",
                        value=self.get_psna(next_reset),
                        inline=False)

    def get_fractals(self, fractals, ctx, tomorrow=False):
        recommended_fractals = []
        daily_fractals = []
        fractals_data = self.gamedata["fractals"]
        for fractal in fractals:
            fractal_level = fractal.replace("Daily Recommended Fractal—Scale ",
                                            "")
            if re.match("[0-9]{1,3}", fractal_level):
                recommended_fractals.append(fractal_level)
            else:
                line = self.get_emoji(ctx, "daily fractal") + re.sub(
                    r"(?:Daily|Tier 4) ", "", fractal)
                try:
                    scale = self.gamedata["fractals"][fractal[13:]][-1]
                    instabilities = self.get_instabilities(scale,
                                                           ctx=ctx,
                                                           tomorrow=tomorrow)
                    if instabilities:
                        line += f"\n{instabilities}"
                except (IndexError, KeyError):
                    pass
                daily_fractals.append(line)
        for i, level in enumerate(sorted(recommended_fractals, key=int)):
            for k, v in fractals_data.items():
                if int(level) in v:
                    recommended_fractals[i] = "{}{} {}".format(
                        self.get_emoji(ctx, "daily recommended fractal"),
                        level, k)

        return (
            daily_fractals,
            recommended_fractals,
            self.get_cm_instabilities(ctx=ctx, tomorrow=tomorrow),
        )

    def get_psna(self, when=None):
        """The Pact Supply Network Agents at `when` (default: now)."""
        if when is None:
            when = datetime.datetime.now(datetime.timezone.utc)
        return self.gamedata["pact_supply"][(when - PSNA_RESET).weekday()]

    def get_instabilities(self, fractal_level, *, tomorrow=False, ctx=None):
        fractal_level = str(fractal_level)
        day = self.get_year_day(tomorrow=tomorrow)
        if fractal_level not in self.instabilities["instabilities"]:
            return None
        levels = self.instabilities["instabilities"][fractal_level][day]
        names = []
        for instab in levels:
            name = self.instabilities["instability_names"][instab]
            if ctx:
                name = (en_space + tab +
                        self.get_emoji(ctx, name.replace(",", "")) + name)
            names.append(name)
        return "\n".join(names)

    def get_cm_instabilities(self, *, ctx=None, tomorrow=False):
        cm_instabs = []
        cm_fractals = "Nightmare", "Shattered Observatory", "Sunqua Peak", "Silent Surf", "Lonely Tower"
        for fractal in cm_fractals:
            scale = self.gamedata["fractals"][fractal][-1]
            line = self.get_emoji(ctx, "daily fractal") + fractal
            instabilities = self.get_instabilities(scale,
                                                   ctx=ctx,
                                                   tomorrow=tomorrow)
            cm_instabs.append(line + "\n" + instabilities)
        return "\n".join(cm_instabs)

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

    @tasks.loop(time=[datetime.time(hour=23, minute=40, tzinfo=datetime.timezone.utc)])
    async def send_daily_notifs(self):
        try:
            await self.cache_dailies()
        except Exception:
            # Post from the cache the refresh loop keeps
            self.log.exception("Exception caching dailies before posting them")
        cursor = self.guild_subdocs("daily", {"daily.on": True, "daily.channel": {"$ne": None}})
        daily_doc = await self.bot.data.config.get()

        async def notify_guild(doc):
            categories = doc.get("categories")
            channel = self.bot.get_channel(doc["channel"])

            if not channel:
                return
            can_embed = channel.permissions_for(channel.guild.me).embed_links
            can_send = channel.permissions_for(channel.guild.me).send_messages
            can_see_history = channel.permissions_for(
                channel.guild.me
            ).read_message_history
            if not can_send:
                return
            if not can_embed:
                return await channel.send(
                    "Need permission to "
                    "embed links in order "
                    "to send daily "
                    "notifs!"
                )
            try:
                embed = await self.daily_embed(
                    categories, doc=daily_doc, interaction=channel, tomorrow=True
                )
            except ValueError:
                return
            embed.title = "Dailies"
            tomorrow = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(days=1)
            tomorrow = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            embed.timestamp = tomorrow
            edit = doc.get("autoedit", False)
            autodelete = doc.get("autodelete", False)
            old_message = None
            if (autodelete or edit) and can_see_history:
                try:
                    old_message_id = doc.get("message")
                    if old_message_id:
                        old_message = await channel.fetch_message(old_message_id)
                except discord.HTTPException:
                    pass
            edited = False
            embed.set_thumbnail(
                url="https://wiki.guildwars2.com/images/" "1/14/Daily_Achievement.png"
            )
            if old_message and edit:
                try:
                    await old_message.edit(embed=embed)
                    edited = True
                except discord.HTTPException:
                    pass
            if not edited:
                message = await channel.send(embed=embed)
            if old_message and autodelete and not edited:
                try:
                    await old_message.delete()
                except discord.HTTPException:
                    pass
            if not edited:
                await self.bot.data.guilds.update(channel.guild.id, {"daily.message": message.id})
            autopin = doc.get("autopin", False)
            if autopin:
                if edited:
                    message = old_message
                    if message.pinned:
                        return
                try:
                    await message.pin()
                    try:
                        if can_see_history:
                            async for m in channel.history(after=message, limit=3):
                                if (
                                    m.type == discord.MessageType.pins_add
                                    and m.author == self.bot.user
                                ):
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
            self.run_in_background(notify_guild(doc), f"posting dailies to server {doc['_id']}")
            await asyncio.sleep(0.1)

    @send_daily_notifs.error
    async def swap_daily_tomorrow_and_today_error(self, error):
        self.log.exception("Error while sending dailies", exc_info=error)
        self.send_daily_notifs.restart()

    @send_daily_notifs.before_loop
    async def before_daily_checker(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Daily(bot))
