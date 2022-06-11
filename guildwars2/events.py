import asyncio
import datetime
from dis import disco

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks

UTC_TZ = datetime.timezone.utc

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
    "name": "EoD- End of Dragons"
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
        update_result = await self.cog.bot.database.set(
            interaction.user,
            {"event_reminders": {
                "last_message": interaction.message.id,
            }},
            self.cog,
            operator="pull",
        )
        if update_result.modified_count:
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass
        await interaction.response.send_message('Unsubscribed!',
                                                ephemeral=True)


class EventsMixin:

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

    async def event_name_autocomplete(self, interaction: discord.Interaction,
                                      current):
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
                        names.add(boss["name"])
            else:
                for subcategory in timers[category]:
                    for event in subcategory["phases"]:
                        if event["name"]:
                            names.add(event["name"])
        return sorted([
            Choice(name=n, value=n) for n in names if current in n.lower()
        ][:25],
                      key=lambda c: c.name)

    @app_commands.command()
    @app_commands.describe(
        event_name="Event name. Examples: Shadow Behemoth. Gerent Preparation",
        minutes_before_event="The number of minutes before "
        "the event that you'll be notified at")
    @app_commands.autocomplete(event_name=event_name_autocomplete)
    async def event_reminder(self,
                             interaction: discord.Interaction,
                             event_name: str,
                             minutes_before_event: int = 5):
        """Make the bot automatically notify you before an event starts"""
        if minutes_before_event < 0:
            return await interaction.response.send_message(
                "That's not how time works!", ephemeral=True)
        if minutes_before_event > 60:
            return await interaction.response.send_message(
                "Time can't be greater than one hour", ephemeral=True)
        event_name = event_name.lower()
        reminder = {}
        for boss in self.boss_schedule:
            if boss["name"].lower() == event_name:
                reminder["type"] = "boss"
                reminder["name"] = boss["name"]
        if not reminder:
            for group in "hot", "pof", "day", "ibs", "eod":
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
                "No event found matching that name", ephemeral=True)
        reminder["time"] = minutes_before_event * 60
        await self.bot.database.set(interaction.user,
                                    {"event_reminders": reminder},
                                    self,
                                    operator="push")
        await interaction.response.send_message("Reminder set succesfully",
                                                ephemeral=True)

    async def et_reminder_settings_menu(self, ctx):
        # Unimplemented. Should get around to it sometime.
        user = ctx.author
        embed_templates = [
            {
                "setting":
                "online_only",
                "title":
                "Online only",
                "description":
                "Enable to have reminders sent only when you're online on Discord",
                "footer":
                "Note that the bot can't distinguish whether you're invisible or offline",
            },
            {
                "setting":
                "ingame_only",
                "title":
                "Ingame only",
                "description":
                "Enable to have reminders sent only while you're in game",
                "footer":
                "This works based off your Discord game status. Make sure to enable it",
            },
        ]
        doc = await self.bot.database.get(user, self)
        doc = doc.get("et_reminder_settings", {})
        settings = [t["setting"] for t in embed_templates]
        settings = {s: doc.get(s, False) for s in settings}
        messages = []
        reactions = {"✔": True, "❌": False}
        to_cleanup = [
            await user.send("Use reactions below to configure reminders")
        ]

        def setting_embed(template):
            enabled = "enabled" if settings[
                template["setting"]] else "disabled"
            description = (f"**{template['description']}**\n"
                           f"Current state: **{enabled}**")
            embed = discord.Embed(title=template["title"],
                                  description=description,
                                  color=self.embed_color)
            if template["footer"]:
                embed.set_footer(text=template["footer"])
            return embed

        for template in embed_templates:
            embed = setting_embed(template)
            msg = await user.send(embed=embed)
            messages.append({"message": msg, "setting": template["setting"]})
            to_cleanup.append(msg)
            for reaction in reactions:
                asyncio.create_task(msg.add_reaction(reaction))

        def check(r, u):
            if not isinstance(r.emoji, str):
                return False
            if u != user:
                return False
            return r.emoji in reactions and r.message.id in [
                m["message"].id for m in messages
            ]

        while True:
            try:
                reaction, _ = await self.bot.wait_for("reaction_add",
                                                      check=check,
                                                      timeout=120)
            except asyncio.TimeoutError:
                break
            setting = next(m["setting"] for m in messages
                           if m["message"].id == reaction.message.id)
            settings[setting] = reactions[reaction.emoji]
            template = next(t for t in embed_templates
                            if t["setting"] == setting)
            embed = setting_embed(template)
            asyncio.create_task(reaction.message.edit(embed=embed))
            await self.bot.database.set(user,
                                        {"et_reminder_settings": settings},
                                        self)
        for message in to_cleanup:
            asyncio.create_task(message.delete())

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
            icon_url=self.bot.user.avatar.url,
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
                         icon_url=self.bot.user.avatar.url)
        return embed

    async def get_timezone(self, guild):
        if not guild:
            return UTC_TZ
        doc = await self.bot.database.get_guild(guild, self)
        if not doc:
            return UTC_TZ
        tz = doc.get("timezone")
        if tz:
            offset = datetime.timedelta(hours=tz)
            tz = datetime.timezone(offset)
        return tz or UTC_TZ

    def get_time_until_event(self, reminder):
        if reminder["type"] == "boss":
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
        time = datetime.datetime.utcnow()
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

        if time < reminder["time"] + 30:
            last_reminded = reminder.get("last_reminded")
            if (last_reminded and
                (datetime.datetime.utcnow() - last_reminded).total_seconds()
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
                return
            reminder["last_reminded"] = msg.created_at
            reminder["last_message"] = msg.id
            await self.bot.database.set(user,
                                        {f"event_reminders.{i}": reminder},
                                        self)

    @tasks.loop(seconds=10)
    async def event_reminder_task(self):
        cursor = self.bot.database.iter(
            "users", {"event_reminders": {
                "$exists": True,
                "$ne": []
            }}, self)
        async for doc in cursor:
            try:
                user = doc["_obj"]
                if not user:
                    continue
                for i, reminder in enumerate(doc["event_reminders"]):
                    asyncio.create_task(
                        self.process_reminder(user, reminder, i))
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    @event_reminder_task.before_loop
    async def before_event_reminder_task(self):
        await self.bot.wait_until_ready()
