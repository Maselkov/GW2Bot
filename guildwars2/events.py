import datetime

import discord
from discord.ext import commands


class EventsMixin:
    @commands.command(aliases=["eventtimer", "eventtimers"])
    async def et(self, ctx):
        """The event timer. Shows upcoming world bosses."""
        embed = self.schedule_embed(self.get_upcoming_bosses())
        try:
            await ctx.send(embed=embed)
        except:
            await ctx.send("Need permission to embed links")

    def generate_schedule(self):
        time = datetime.datetime(1, 1, 1)
        normal = self.gamedata["event_timers"]["bosses"]["normal"]
        hardcore = self.gamedata["event_timers"]["bosses"]["hardcore"]
        schedule = []
        counter = 0
        while counter < 12:
            for boss in normal:
                increment = datetime.timedelta(
                    hours=boss["interval"] * counter)
                time = (datetime.datetime(1, 1, 1, *boss["start_time"]) +
                        increment)
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

    def get_upcoming_bosses(self, timezone=None):
        upcoming_bosses = []
        time = datetime.datetime.utcnow()
        counter = 0
        day = 0
        done = False
        while not done:
            for boss in self.boss_schedule:
                if counter == 8:
                    done = True
                    break
                boss_time = datetime.datetime.strptime(boss["time"],
                                                       "%H:%M:%S")
                boss_time = boss_time.replace(
                    year=time.year, month=time.month,
                    day=time.day) + datetime.timedelta(days=day)
                if time < boss_time:
                    output = {
                        "name": boss["name"],
                        "time": str(boss_time.time()),
                        "waypoint": boss["waypoint"],
                        "diff": self.format_timedelta((boss_time - time))
                    }
                    upcoming_bosses.append(output)
                    counter += 1
            day += 1
        return upcoming_bosses

    def schedule_embed(self, schedule):
        data = discord.Embed()
        for boss in schedule:
            value = "Time: {}\nWaypoint: {}".format(boss["time"],
                                                    boss["waypoint"])
            data.add_field(
                name="{} in {}".format(boss["name"], boss["diff"]),
                value=value,
                inline=False)
        data.set_author(name="Upcoming world bosses")
        data.set_footer(
            text="All times are for UTC. Timezone support coming soon™")
        return data

    def format_timedelta(self, td):
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return "{} hours and {} minutes".format(hours, minutes)
        else:
            return "{} minutes".format(minutes)
