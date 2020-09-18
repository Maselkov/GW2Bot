import datetime
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIKeyError


class DailyMixin:
    @commands.group(aliases=["d"], case_insensitive=True)
    async def daily(self, ctx):
        """Commands showing daily things"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @daily.command(name="pve", aliases=["e"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_pve(self, ctx):
        """Show today's PvE dailies"""
        embed = await self.daily_embed(["pve"], ctx=ctx)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="wvw", aliases=["w"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_wvw(self, ctx):
        """Show today's WvW dailies"""
        embed = await self.daily_embed(["wvw"], ctx=ctx)
        embed.set_thumbnail(
            url="https://render.guildwars2.com/file/"
            "2BBA251A24A2C1A0A305D561580449AF5B55F54F/338457.png")
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="pvp", aliases=["p"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_pvp(self, ctx):
        """Show today's PvP dailies"""
        embed = await self.daily_embed(["pvp"], ctx=ctx)
        try:
            embed.set_thumbnail(
                url="https://render.guildwars2.com/file/"
                "FE01AF14D91F52A1EF2B22FE0A552B9EE2E4C3F6/511340.png")
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="fractals", aliases=["f"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_fractals(self, ctx):
        """Show today's fractal dailies"""
        embed = await self.daily_embed(["fractals"], ctx=ctx)
        try:
            embed.set_thumbnail(
                url="https://render.guildwars2.com/file/"
                "4A5834E40CDC6A0C44085B1F697565002D71CD47/1228226.png")
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="strikes", aliases=["s"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_strikes(self, ctx):
        """Show today's priority strike"""
        embed = await self.daily_embed(["strikes"], ctx=ctx)
        try:
            embed.set_thumbnail(
                url="https://render.guildwars2.com/file/"
                "C34A20B86C73B0DCDC9401ECD22CE37C36B018A7/2271016.png")
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="psna")
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_psna(self, ctx):
        """Show today's Pact Supply Network Agent locations"""
        embed = await self.daily_embed(["psna"], ctx=ctx)
        embed.set_thumbnail(
            url="https://wiki.guildwars2.com/images/1/14/Daily_Achievement.png"
        )
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="all", aliases=["a"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_all(self, ctx):
        """Show today's all dailies"""
        embed = await self.daily_embed(
            ["psna", "pve", "pvp", "wvw", "fractals", "strikes"], ctx=ctx)
        embed.set_thumbnail(
            url="https://wiki.guildwars2.com/images/1/14/Daily_Achievement.png"
        )
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    async def daily_embed(self, categories, *, doc=None, ctx=None):
        if not doc:
            doc = await self.bot.database.get_cog_config(self)
        if ctx:
            color = await self.get_embed_color(ctx)
        else:
            color = self.embed_color
        embed = discord.Embed(title="Dailies", color=color)
        dailies = doc["cache"]["dailies"]
        for category in categories:
            if category == "psna" and datetime.datetime.utcnow().hour >= 8:
                value = "\n".join(dailies["psna_later"])
            elif category == "fractals":
                fractals = self.get_fractals(dailies["fractals"], ctx)
                value = "\n".join(fractals)
            elif category == "strikes":
                category = "Priority Strike"
                strikes = self.get_strike(ctx)
                value = strikes
            else:
                lines = []
                for i, d in enumerate(dailies[category]):
                    # HACK handling for emojis for lws dailies. Needs rewrite
                    emoji = self.get_emoji(ctx, f"daily {category}")
                    if category == "pve":
                        if i == 5:
                            emoji = self.get_emoji(ctx, f"daily lws3")
                        elif i == 6:
                            emoji = self.get_emoji(ctx, f"daily lws4")
                    lines.append(emoji + d)
                value = "\n".join(lines)
            if category == "psna_later":
                category = "psna in 8 hours"
            value = re.sub(r"(?:Daily|Tier 4|PvP|WvW) ", "", value)
            if category.startswith("psna"):
                category = self.get_emoji(ctx, "daily psna") + category
            embed.add_field(name=category.upper(), value=value, inline=False)
        embed.set_footer(text=self.bot.user.name,
                         icon_url=self.bot.user.avatar_url)
        return embed

    def get_lw_dailies(self):
        LWS3_MAPS = [
            "Bloodstone Fen", "Ember Bay", "Bitterfrost Frontier",
            "Lake Doric", "Draconis Mons", "Siren's Landing"
        ]
        LWS4_MAPS = [
            "Domain of Istan", "Sandswept Isles", "Domain of Kourna",
            "Jahai Bluffs", "Thunderhead Peaks", "Dragonfall"
        ]
        start_date = datetime.date(year=2020, month=5, day=30)
        days = (datetime.datetime.utcnow().date() - start_date).days
        index = days % (len(LWS3_MAPS))
        lines = []
        lines.append(f"Daily Living World Season 3 - {LWS3_MAPS[index]}")
        lines.append(f"Daily Living World Season 4 - {LWS4_MAPS[index]}")
        return lines

    def get_fractals(self, fractals, ctx):
        recommended_fractals = []
        daily_fractals = []
        fractals_data = self.gamedata["fractals"]
        for fractal in fractals:
            fractal_level = fractal.replace("Daily Recommended Fractal—Scale ",
                                            "")
            if re.match("[0-9]{1,3}", fractal_level):
                recommended_fractals.append(fractal_level)
            else:
                daily_fractals.append(
                    self.get_emoji(ctx, "daily fractal") + fractal)
        for i, level in enumerate(sorted(recommended_fractals, key=int)):
            for k, v in fractals_data.items():
                if int(level) in v:
                    recommended_fractals[i] = "{}{} {}".format(
                        self.get_emoji(ctx, "daily recommended fractal"),
                        level, k)
        return ["> **DAILY**"] + daily_fractals + ["> **RECOMMENDED**"
                                                   ] + recommended_fractals

    def get_psna(self, *, offset_days=0):
        offset = datetime.timedelta(hours=-8)
        tzone = datetime.timezone(offset)
        day = datetime.datetime.now(tzone).weekday()
        if day + offset_days > 6:
            offset_days = -6
        return self.gamedata["pact_supply"][day + offset_days]

    def get_strike(self, ctx):
        start_date = datetime.date(year=2020, month=8, day=30)
        days = (datetime.datetime.utcnow().date() - start_date).days
        index = days % len(self.gamedata["strike_missions"])
        return self.get_emoji(
            ctx, "daily strike") + self.gamedata["strike_missions"][index]
