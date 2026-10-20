"""Event timers: /et, /reminder event and its reminders, and the boss notifier."""
import asyncio
import datetime
import logging

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import tasks

from .base import GW2Cog

UTC_TZ = datetime.timezone.utc


def naive_utcnow():
    """The time in UTC, naive like the dates MongoDB returns."""
    return datetime.datetime.now(UTC_TZ).replace(tzinfo=None)

ET_CATEGORIES = [{
    "value": "hot",
    "name": "HoT - Heart of Thorns"
}, {
    "value": "pof",
    "name": "PoF - Path of Fire"
}, {
    "value": "ibs",
    "name": "IBS - The Icebrood Saga"
}, {
    "value": "eod",
    "name": "EoD - End of Dragons"
}, {
    "value": "soto",
    "name": "SotO - Secrets of the Obscure"
}, {
    "value": "day",
    "name": "Day/night cycle"
}, {
    "value": "bosses",
    "name": "World bosses"
}]


class EventTimerReminderUnsubscribeView(discord.ui.View):

    def __init__(self, cog):
        self.cog = cog
        super().__init__(timeout=None)

    @discord.ui.button(style=discord.ButtonStyle.red,
                       emoji="❌",
                       label="Unsubscribe",
                       custom_id="et:unsubscribe")
    async def unsubscribe(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        update_result = await self.cog.bot.data.users.update(
            interaction.user.id,
            {"event_reminders": {
                "last_message": interaction.message.id,
            }},
            op="pull",
        )
        if update_result.modified_count:
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass
        await interaction.response.send_message('Unsubscribed!',
                                                ephemeral=True)


class Events(GW2Cog):

    reminder_group = app_commands.Group(
        name="reminder", description="Commands for setting various personal reminders."
    )

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)
        self.boss_schedule = self.generate_schedule()

    async def cog_load(self):
        # Reminder DMs' Unsubscribe buttons keep working across restarts
        self.bot.add_view(EventTimerReminderUnsubscribeView(self))
        self.event_reminder_task.start()
        self.boss_notifier.start()

    async def cog_unload(self):
        self.event_reminder_task.cancel()
        self.boss_notifier.cancel()

    @app_commands.command()
    @app_commands.describe(category="Event timer category")
    @app_commands.choices(category=[Choice(**c) for c in ET_CATEGORIES])
    async def et(self, interaction: discord.Interaction, category: str):
        """Event timer"""
        if category == "bosses":
            embed = self.schedule_embed()
        else:
            embed = await self.timer_embed(interaction, category)
        await interaction.response.send_message(embed=embed)

    def generate_schedule(self):
        now = datetime.datetime.now(UTC_TZ)
        normal = self.gamedata["event_timers"]["bosses"]["normal"]
        hardcore = self.gamedata["event_timers"]["bosses"]["hardcore"]
        schedule = []
        counter = 0
        while counter < 12:
            for boss in normal:
                increment = datetime.timedelta(hours=boss["interval"] *
                                               counter)
                time = (datetime.datetime(
                    1, 1, 1, *boss["start_time"], tzinfo=UTC_TZ) + increment)
                if time.day != 1:
                    continue
                time = time.replace(year=now.year,
                                    month=now.month,
                                    day=now.day,
                                    tzinfo=UTC_TZ)
                output = {
                    "name": boss["name"],
                    "time": time,
                    "waypoint": boss["waypoint"],
                }
                schedule.append(output)
            counter += 1
        for boss in hardcore:
            for hours in boss["times"]:
                time = datetime.datetime.now(UTC_TZ)
                time = time.replace(hour=hours[0], minute=hours[1])
                output = {
                    "name": boss["name"],
                    "time": time,
                    "waypoint": boss["waypoint"],
                }
                schedule.append(output)
        return sorted(schedule, key=lambda t: t["time"].time())

    def get_upcoming_bosses(self, limit=8):
        upcoming_bosses = []
        time = datetime.datetime.now(UTC_TZ)
        counter = 0
        day = 0
        done = False
        while not done:
            for boss in self.boss_schedule:
                if counter == limit:
                    done = True
                    break
                boss_time = boss["time"]
                boss_time = boss_time + datetime.timedelta(days=day)
                if time < boss_time:
                    output = {
                        "name": boss["name"],
                        "time": f"<t:{int(boss_time.timestamp())}:t>",
                        "waypoint": boss["waypoint"],
                        "diff": boss_time - time,
                    }
                    upcoming_bosses.append(output)
                    counter += 1
            day += 1
        return upcoming_bosses

    def schedule_embed(self, limit=8):
        schedule = self.get_upcoming_bosses(limit)
        data = discord.Embed(title="Upcoming world bosses",
                             color=self.embed_color)
        for boss in schedule:
            value = "Time: {}\nWaypoint: {}".format(boss["time"],
                                                    boss["waypoint"])
            data.add_field(
                name="{} in {}".format(boss["name"],
                                       self.format_timedelta(boss["diff"])),
                value=value,
                inline=False,
            )
        data.set_footer(
            text="The timestamps are dynamically adjusted to your timezone",
            icon_url=self.bot.user.display_avatar.url,
        )
        return data

    def format_timedelta(self, td):
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return "{} hours and {} minutes".format(hours, minutes)
        else:
            return "{} minutes".format(minutes)

    async def timer_embed(self, ctx, group):
        time = datetime.datetime.now(datetime.timezone.utc)
        position = (
            60 * time.hour + time.minute
        ) % 120  # this gets the minutes elapsed in the current 2 hour window
        maps = self.gamedata["event_timers"][group]
        title = {
            "hot": "HoT Event Timer",
            "pof": "PoF Event Timer",
            "day": "Day/Night cycle",
            "eod": "End of Dragons",
            "soto": "Secrets of the Obscure",
            "ibs": "The Icebrood Saga"
        }.get(group)
        embed = discord.Embed(title=title,
                              color=await self.get_embed_color(ctx))
        for location in maps:
            duration_so_far = 0
            current_phase = None
            index = 0
            phases = location["phases"]
            # TODO null handling
            for i, phase in enumerate(phases):
                if position < duration_so_far:
                    break
                current_phase = phase["name"]
                index = i
                duration_so_far += phase["duration"]
            double = phases + phases
            for phase in double[index + 1:]:
                if not phase["name"]:
                    duration_so_far += phase["duration"]
                    continue
                if phase["name"] == current_phase:
                    duration_so_far += phase["duration"]
                    continue
                break
            next_phase = phase["name"]
            time_until = duration_so_far - position
            event_time = time + datetime.timedelta(minutes=time_until)
            timestamp = f"<t:{int(event_time.timestamp())}:R>"
            if current_phase:
                current = f"Current phase: **{current_phase}**"
            else:
                current = "No events currently active."
            value = (current +
                     "\nNext phase: **{}** {}".format(next_phase, timestamp))
            embed.add_field(name=location["name"], value=value, inline=False)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.display_avatar.url)
        return embed

    def get_time_until_event(self, reminder):
        """Seconds until the reminder's event, or None if it isn't in the
        schedule (e.g. renamed in the game data since)."""
        if reminder["type"] == "boss":
            if not any(boss["name"] == reminder["name"]
                       for boss in self.boss_schedule):
                return None
            time = datetime.datetime.now(UTC_TZ)
            day = 0
            done = False
            while not done:
                for boss in self.boss_schedule:
                    boss_time = boss["time"]
                    boss_time = boss_time + datetime.timedelta(days=day)
                    if time < boss_time:
                        if boss["name"] == reminder["name"]:
                            return int((
                                boss_time -
                                datetime.datetime.now(UTC_TZ)).total_seconds())
                day += 1
        time = datetime.datetime.now(UTC_TZ)
        position = (60 * time.hour + time.minute) % 120
        for location in self.gamedata["event_timers"][reminder["group"]]:
            if location["name"] == reminder["map_name"]:
                duration_so_far = 0
                index = 0
                phases = location["phases"]
                for i, phase in enumerate(phases):
                    if position < duration_so_far:
                        break
                    index = i
                    duration_so_far += phase["duration"]
                index += 1
                if index == len(phases):
                    if phases[0]["name"] == phases[index - 1]["name"]:
                        index = 1
                        duration_so_far += phases[0]["duration"]
                    else:
                        index = 0
                for phase in phases[index:]:
                    if phase["name"] == reminder["name"]:
                        break
                    duration_so_far += phase["duration"]
                else:
                    for phase in phases:
                        if phase["name"] == reminder["name"]:
                            break
                        duration_so_far += phase["duration"]
                return (duration_so_far - position) * 60

    # TODO
    async def process_reminder(self, user, reminder, i):
        time = self.get_time_until_event(reminder)
        if time is None:
            return
        if time < reminder["time"] + 30:
            last_reminded = reminder.get("last_reminded")
            if (last_reminded and
                (naive_utcnow() - last_reminded.replace(tzinfo=None)).total_seconds()
                    < reminder["time"] + 120):
                return
            try:
                last_message = reminder.get("last_message")
                if last_message:
                    last_message = await user.fetch_message(last_message)
                    await last_message.delete()
            except discord.HTTPException:
                pass
            when = datetime.datetime.now(
                datetime.timezone.utc) + datetime.timedelta(seconds=time)
            timestamp = f"<t:{int(when.timestamp())}:R>"
            description = f"{reminder['name']} will begin {timestamp}"
            embed = discord.Embed(title="Event reminder",
                                  description=description,
                                  color=self.embed_color)
            # try:
            try:
                msg = await user.send(
                    embed=embed, view=EventTimerReminderUnsubscribeView(self))
            except discord.HTTPException:
                # Closed DMs: count this spawn as reminded rather than
                # trying again every 10 seconds until it starts
                reminder["last_reminded"] = naive_utcnow()
                reminder.pop("last_message", None)
            else:
                reminder["last_reminded"] = msg.created_at
                reminder["last_message"] = msg.id
            await self.bot.data.users.update(user.id, {f"event_reminders.{i}": reminder})

    @tasks.loop(seconds=10)
    async def event_reminder_task(self):
        cursor = self.bot.data.users.find({"event_reminders": {"$exists": True, "$ne": []}})
        async for doc in cursor:
            try:
                user = self.bot.get_user(doc["_id"])
                if not user:
                    continue
                for i, reminder in enumerate(doc["event_reminders"]):
                    self.run_in_background(self.process_reminder(user, reminder, i),
                                           f"reminding user {user.id} of {reminder.get('name')}")
            except asyncio.CancelledError:
                return
            except Exception:
                self.log.exception("Couldn't check user %s's event reminders", doc.get("_id"))

    @event_reminder_task.before_loop
    async def before_event_reminder_task(self):
        await self.bot.wait_until_ready()

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

    @tasks.loop(minutes=5)
    async def boss_notifier(self):
        boss = self.get_upcoming_bosses(1)[0]
        await asyncio.sleep(boss["diff"].total_seconds() + 1)
        cursor = self.bot.data.guilds.find({"bossnotifs.on": True, "bossnotifs.channel": {"$ne": None}})
        async for doc in cursor:
            guild_id = doc["_id"]
            try:
                doc = doc["bossnotifs"]
                edit = doc.get("edit", False)
                channel = self.bot.get_channel(doc["channel"])
                if not channel:
                    continue
                embed = self.schedule_embed(2)
                old_message_id = doc.get("message")
                edited = False
                try:
                    if edit and old_message_id:
                        try:
                            old_message = await channel.fetch_message(old_message_id)
                            await old_message.edit(embed=embed)
                            edited = True
                            continue
                        except discord.NotFound:
                            # Deleted: post a new one to edit from now on
                            old_message_id = None
                        except discord.HTTPException:
                            pass
                    message = await channel.send(embed=embed)
                except discord.Forbidden:
                    try:
                        await channel.send(
                            "Need permission to "
                            "embed links in order "
                            "to send boss "
                            "notifs!"
                        )
                    except discord.Forbidden:
                        # Can't post there at all: stop trying, like news
                        await self.bot.data.guilds.update(guild_id, {"bossnotifs.on": False})
                    continue
                if not edited:
                    await self.bot.data.guilds.update(guild_id, {"bossnotifs.message": message.id})
                    if old_message_id:
                        try:
                            to_delete = await channel.fetch_message(old_message_id)
                            await to_delete.delete()
                        except discord.HTTPException:
                            pass
            except asyncio.CancelledError:
                return
            except Exception:
                self.log.exception("Couldn't post boss notifications in server %s", guild_id)
            await asyncio.sleep(0.1)

    @boss_notifier.before_loop
    async def before_boss_notifier(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Events(bot))
