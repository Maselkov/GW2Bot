import datetime

from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError


class DailyMixin:
    @commands.group(aliases=["d"])
    async def daily(self, ctx):
        """Commands showing daily things"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @daily.command(name="pve", aliases=["e", "E", "PVE"])
    @commands.cooldown(1, 10, BucketType.user)
    async def daily_pve(self, ctx):
        """Show today's PvE dailies"""
        try:
            output = await self.daily_handler("pve")
        except APIError as e:
            return await self.error_handler(ctx, e)
        await ctx.send(output)

    @daily.command(name="wvw", aliases=["w", "WVW", "W"])
    @commands.cooldown(1, 10, BucketType.user)
    async def daily_wvw(self, ctx):
        """Show today's WvW dailies"""
        try:
            output = await self.daily_handler("wvw")
        except APIError as e:
            return await self.error_handler(ctx, e)
        await ctx.send(output)

    @daily.command(name="pvp", aliases=["p", "P", "PVP"])
    @commands.cooldown(1, 10, BucketType.user)
    async def daily_pvp(self, ctx):
        """Show today's PvP dailies"""
        try:
            output = await self.daily_handler("pvp")
        except APIError as e:
            return await self.error_handler(ctx, e)
        await ctx.send(output)

    @daily.command(name="fractals", aliases=["f", "F", "Fractals"])
    @commands.cooldown(1, 10, BucketType.user)
    async def daily_fractals(self, ctx):
        """Show today's fractal dailie"""
        try:
            output = await self.daily_handler("fractals")
        except APIError as e:
            return await self.error_handler(ctx, e)
        await ctx.send(output)

    @daily.command(name="psna")
    @commands.cooldown(1, 10, BucketType.user)
    async def daily_psna(self, ctx):
        """Show today's Pact Supply Network Agent locations"""
        output = ("Paste this into chat for pact supply network agent "
                  "locations: ```{0}```".format(self.get_psna()))
        await ctx.send(output)

    @daily.command(name="all", aliases=["A", "a"])
    @commands.cooldown(1, 10, BucketType.user)
    async def daily_all(self, ctx):
        """Show today's all dailies"""
        try:
            results = await self.call_api("achievements/daily")
        except APIError as e:
            return await self.error_handler(ctx, e)
        output = await self.display_all_dailies(results)
        await ctx.send("```markdown\n" + output + "```")

    async def daily_handler(self, search):
        endpoint = "achievements/daily"
        results = await self.call_api(endpoint)
        data = results[search]
        dailies = []
        daily_format = []
        daily_filtered = []
        for x in data:
            if x["level"]["max"] == 80:
                dailies.append(x)
        for daily in dailies:
            d = await self.db.achievements.find_one({"_id": daily["id"]})
            daily_format.append(d)
        if search == "fractals":
            for daily in daily_format:
                if not daily["name"].startswith("Daily Tier"):
                    daily_filtered.append(daily)
                if daily["name"].startswith("Daily Tier 4"):
                    daily_filtered.append(daily)
        else:
            daily_filtered = daily_format
        output = "{0} dailes for today are: ```".format(search.capitalize())
        for x in daily_filtered:
            output += "\n" + x["name"]
        output += "```"
        return output

    async def display_all_dailies(self, dailylist, tomorrow=False):
        dailies = ["#Daily PSNA:", self.get_psna()]
        if tomorrow:
            dailies[0] = "#PSNA at this time:"
            dailies.append("#PSNA in 8 hours:")
            dailies.append(self.get_psna(1))
        fractals = []
        sections = ["pve", "pvp", "wvw", "fractals"]
        for x in sections:
            section = dailylist[x]
            dailies.append("#{0} DAILIES:".format(x.upper()))
            if x == "fractals":
                for x in section:
                    d = await self.db.achievements.find_one({"_id": x["id"]})
                    fractals.append(d)
                for frac in fractals:
                    if not frac["name"].startswith("Daily Tier"):
                        dailies.append(frac["name"])
                    if frac["name"].startswith("Daily Tier 4"):
                        dailies.append(frac["name"])
            else:
                for x in section:
                    if x["level"]["max"] == 80:
                        d = await self.db.achievements.find_one({
                            "_id": x["id"]
                        })
                        dailies.append(d["name"])
        return "\n".join(dailies)

    def get_psna(self, modifier=0):
        offset = datetime.timedelta(hours=-8)
        tzone = datetime.timezone(offset)
        day = datetime.datetime.now(tzone).weekday()
        if day + modifier > 6:
            modifier = -6
        return self.gamedata["pact_supply"][day + modifier]
