import datetime
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType


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
            ["psna", "pve", "pvp", "wvw", "fractals"], ctx=ctx)
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
                fractals = self.get_fractals(dailies["fractals"])
                value = "\n".join(fractals)
            else:
                value = "\n".join(dailies[category])
            if category == "psna_later":
                category = "psna in 8 hours"
            value = re.sub(r"(?:Daily|Tier 4|PvP|WvW) ", "", value)
            embed.add_field(name=category.upper(), value=value, inline=False)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.avatar_url)
        return embed

    def get_fractals(self, fractals):
        daily_recs = []
        fractal_final = []
        fractals_data = self.gamedata["fractals"]
        for fractal in fractals:
            fractal_level = fractal.replace("Daily Recommended Fractal—Scale ",
                                            "")
            if re.match("[0-9]{1,3}", fractal_level):
                daily_recs.append(fractal_level)
            else:
                fractal_final.append(fractal)
        for level in sorted(daily_recs, key=int):
            for k, v in fractals_data.items():
                if int(level) in v:
                    fractal_final.append("Recommended - {} {}".format(
                        level, k))
        return fractal_final

    def get_psna(self, *, offset_days=0):
        offset = datetime.timedelta(hours=-8)
        tzone = datetime.timezone(offset)
        day = datetime.datetime.now(tzone).weekday()
        if day + offset_days > 6:
            offset_days = -6
        return self.gamedata["pact_supply"][day + offset_days]
