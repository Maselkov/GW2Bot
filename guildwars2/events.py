import asyncio
import datetime

import discord
from discord import emoji
from discord.ext import commands, tasks
from discord_slash import cog_ext
from discord_slash.context import ComponentContext
from discord_slash.model import ButtonStyle, SlashCommandOptionType
from discord_slash.utils.manage_components import create_actionrow, create_button

UTC_TZ = datetime.timezone.utc


class EventsMixin:
    @cog_ext.cog_subcommand(base="et",
                            name="hot",
                            base_description="Event timer commands")
    async def et_hot(self, ctx):
        """Event timer for HoT maps and Dry Top"""
        await ctx.send(embed=await self.timer_embed(ctx, "hot"))

    @cog_ext.cog_subcommand(base="et",
                            name="pof",
                            base_description="Event timer commands")
    async def et_pof(self, ctx):
        """Event timer for PoF and LS4 maps"""
        await ctx.send(embed=await self.timer_embed(ctx, "pof"))

    @cog_ext.cog_subcommand(base="et",
                            name="day",
                            base_description="Event timer commands")
    async def et_day(self, ctx):
        """Current day/night cycle"""
        await ctx.send(embed=await self.timer_embed(ctx, "day"))

    @cog_ext.cog_subcommand(base="et",
                            name="bosses",
                            base_description="Event timer commands")
    async def et_bosses(self, ctx):
        """Upcoming world bosses"""
        embed = self.schedule_embed()
        await ctx.send(embed=embed)

    @cog_ext.cog_subcommand(
        base="et",
        name="reminder",
        base_description="Event timer commands",
        options=[{
            "name": "event_name",
            "description":
            "Event name. Examples: Shadow Behemoth. Gerent Preparation",
            "type": SlashCommandOptionType.STRING,
            "required": True,
        }, {
            "name": "minutes_before_event",
            "description":
            "The number of minutes before the event that you'll be notified at",
            "type": SlashCommandOptionType.INTEGER,
            "required": True
        }])
    async def et_reminder(self,
                          ctx,
                          event_name: str,
                          minutes_before_event: int = 5):
        """Make the bot automatically notify you before an event starts"""
        if minutes_before_event < 0:
            return await ctx.send("That's not how time works!", hidden=True)
        if minutes_before_event > 60:
            return await ctx.send("Time can't be greater than one hour",
                                  hidden=True)
        event_name = event_name.lower()
        reminder = {}
        for boss in self.boss_schedule:
            if boss["name"].lower() == event_name:
                reminder["type"] = "boss"
                reminder["name"] = boss["name"]
        if not reminder:
            for group in "hot", "pof":
                maps = self.gamedata["event_timers"][group]
                for location in maps:
                    for phase in location["phases"]:
                        if phase["name"].lower() == event_name:
                            reminder["type"] = "phase"
                            reminder["name"] = phase["name"]
                            reminder["group"] = group
                            reminder["map_name"] = location["name"]
        if not reminder:
            return await ctx.send("No event found matching that name",
                                  hidden=True)
        reminder["time"] = minutes_before_event * 60
        await self.bot.database.set(ctx.author, {"event_reminders": reminder},
                                    self,
                                    operator="push")
        await ctx.send("Reminder set succesfully", hidden=True)

    async def et_reminder_settings_menu(self, ctx):
        # Unimplemented. Should get around to it sometime.
        user = ctx.author
        embed_templates = [{
            "setting":
            "online_only",
            "title":
            "Online only",
            "description":
            "Enable to have reminders sent only when you're online on Discord",
            "footer":
            "Note that the bot can't distinguish whether you're invisible or offline"
        }, {
            "setting":
            "ingame_only",
            "title":
            "Ingame only",
            "description":
            "Enable to have reminders sent only while you're in game",
            "footer":
            "This works based off your Discord game status. Make sure to enable it"
        }]
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
                    "waypoint": boss["waypoint"]
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
                    "waypoint": boss["waypoint"]
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
                        "diff": boss_time - time
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
            data.add_field(name="{} in {}".format(
                boss["name"], self.format_timedelta(boss["diff"])),
                           value=value,
                           inline=False)
        data.set_footer(
            text="The timestamps are dynamically adjusted to your timezone",
            icon_url=self.bot.user.avatar_url)
        return data

    def format_timedelta(self, td):
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return "{} hours and {} minutes".format(hours, minutes)
        else:
            return "{} minutes".format(minutes)

    async def timer_embed(self, ctx, group):
        time = datetime.datetime.utcnow()
        position = (
            60 * time.hour + time.minute
        ) % 120  # this gets the minutes elapsed in the current 2 hour window
        maps = self.gamedata["event_timers"][group]
        title = {
            "hot": "HoT Event Timer",
            "pof": "PoF Event Timer",
            "day": "Day/Night cycle"
        }.get(group)
        embed = discord.Embed(title=title,
                              color=await self.get_embed_color(ctx))
        for location in maps:
            duration_so_far = 0
            current_phase = None
            index = 0
            phases = location["phases"]
            for i, phase in enumerate(phases):
                if position < duration_so_far:
                    break
                current_phase = phase["name"]
                index = i
                duration_so_far += phase["duration"]
            index += 1
            if index == len(phases):
                if phases[0]["name"] == phases[index - 1]["name"]:
                    index = 1
                    duration_so_far += phases[0]["duration"]
                else:
                    index = 0
            next_phase = phases[index]["name"]
            time_until = duration_so_far - position
            value = ("Current phase: **{}**"
                     "\nNext phase: **{}** in **{}** minutes".format(
                         current_phase, next_phase, time_until))
            embed.add_field(name=location["name"], value=value, inline=False)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.avatar_url)
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

    async def process_reminder(self, user, reminder, i):
        time = self.get_time_until_event(reminder)
        if time < reminder["time"] + 30:
            last_reminded = reminder.get("last_reminded")
            if last_reminded and (datetime.datetime.utcnow() - last_reminded
                                  ).total_seconds() < reminder["time"] + 120:
                return
            try:
                last_message = reminder.get("last_message")
                if last_message:
                    last_message = await user.fetch_message(last_message)
                    await last_message.delete()
            except discord.HTTPException:
                pass
            minutes, seconds = divmod(time, 60)
            if minutes:
                time_string = (f"{minutes} minutes and {seconds} seconds")
            else:
                time_string = f"{seconds} seconds"
            description = (f"{reminder['name']} will begin in {time_string}")
            embed = discord.Embed(title="Event reminder",
                                  description=description,
                                  color=self.embed_color)
            button = create_button(style=ButtonStyle.red,
                                   emoji="❌",
                                   label="Unsubscribe")
            components = [create_actionrow(button)]

            try:
                msg = await user.send(embed=embed, components=components)
            except discord.HTTPException:
                return
            reminder["last_reminded"] = msg.created_at
            reminder["last_message"] = msg.id
            reminder["button_id"] = button["custom_id"]
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
            except Exception as e:
                pass

    @commands.Cog.listener()
    async def on_component(self, ctx: ComponentContext):
        if ctx.guild:
            return
        update_result = await self.bot.database.set(
            ctx.author,
            {"event_reminders": {
                "last_message": ctx.origin_message_id,
            }},
            self,
            operator="pull")
        if update_result.modified_count:
            try:
                await ctx.origin_message.delete()
            except discord.HTTPException:
                pass
