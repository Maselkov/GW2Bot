import datetime

import discord
from discord.ext import commands

UTC_TZ = datetime.timezone.utc


class EventsMixin:
    @commands.group(case_insensitive=True, aliases=["hotet"])
    async def et(self, ctx):
        """The event timer"""
        # Help formatter preview
        if ctx.invoked_subcommand is None:
            msg = ("**{0}et bosses | b**: Upcoming bosses\n"
                   "**{0}et hot | h**: Event timer for HoT maps and Dry top\n"
                   "**{0}et pof | p**: Event timer for PoF and LS4 maps\n"
                   "**{0}et day | d** Current day/night".format(ctx.prefix))
            embed = discord.Embed(
                title="Event Timer help",
                description=msg,
                color=await self.get_embed_color(ctx))
            embed.set_footer(
                text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
            info = None
            if ctx.invoked_with.lower() == "hotet":
                info = ("**{0}hotet** has evolved into **{0}et**, use "
                        "**{0}et h** to access the old functionality").format(
                            ctx.prefix)
            try:
                await ctx.send(info, embed=embed)
            except:
                await self.bot.send_cmd_help(ctx)

    @et.command(name="hot", aliases=["h"])
    async def et_hot(self, ctx):
        """Event timer for HoT maps and Dry Top"""
        await ctx.send(embed=await self.timer_embed(ctx, "hot"))

    @et.command(name="pof", aliases=["p"])
    async def et_pof(self, ctx):
        """Event timer for PoF and LS4 maps"""
        await ctx.send(embed=await self.timer_embed(ctx, "pof"))

    @et.command(name="day", aliases=["d"])
    async def et_day(self, ctx):
        """Current day/night cycle"""
        await ctx.send(embed=await self.timer_embed(ctx, "day"))

    @et.command(name="bosses", aliases=["b"])
    async def et_bosses(self, ctx):
        """Upcoming world bosses"""
        tz = await self.get_timezone(ctx.guild)
        embed = self.schedule_embed(timezone=tz)
        await ctx.send(embed=embed)

    def generate_schedule(self):
        time = datetime.datetime(1, 1, 1)
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
                output = {
                    "name": boss["name"],
                    "time": str(time.time()),
                    "waypoint": boss["waypoint"]
                }
                schedule.append(output)
            counter += 1
        for boss in hardcore:
            for hours in boss["times"]:
                output = {
                    "name": boss["name"],
                    "time": str(datetime.time(*hours)),
                    "waypoint": boss["waypoint"]
                }
                schedule.append(output)
        return sorted(
            schedule,
            key=
            lambda t: datetime.datetime.strptime(t["time"], "%H:%M:%S").time())

    def get_upcoming_bosses(self, limit=8, *, timezone=UTC_TZ):
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
                boss_time = datetime.datetime.strptime(boss["time"],
                                                       "%H:%M:%S")
                boss_time = boss_time.replace(
                    year=time.year,
                    month=time.month,
                    day=time.day,
                    tzinfo=UTC_TZ) + datetime.timedelta(days=day)
                if time < boss_time:
                    output = {
                        "name": boss["name"],
                        "time": str(boss_time.astimezone(tz=timezone).time()),
                        "waypoint": boss["waypoint"],
                        "diff": boss_time - time
                    }
                    upcoming_bosses.append(output)
                    counter += 1
            day += 1
        return upcoming_bosses

    def schedule_embed(self, limit=8, *, timezone=UTC_TZ):
        schedule = self.get_upcoming_bosses(limit, timezone=timezone)
        data = discord.Embed(
            title="Upcoming world bosses", color=self.embed_color)
        for boss in schedule:
            value = "Time: {}\nWaypoint: {}".format(boss["time"],
                                                    boss["waypoint"])
            data.add_field(
                name="{} in {}".format(boss["name"],
                                       self.format_timedelta(boss["diff"])),
                value=value,
                inline=False)
        data.set_footer(
            text="Timezone: {}".format(timezone.tzname(None)),
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
        embed = discord.Embed(
            title=title, color=await self.get_embed_color(ctx))
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
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
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
