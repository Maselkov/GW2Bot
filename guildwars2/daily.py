import datetime

from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
import discord


class DailyMixin:
    @commands.group(aliases=["d"])
    async def daily(self, ctx):
        """Commands showing daily things"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @daily.command(name="pve", aliases=["e", "E", "PVE"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_pve(self, ctx):
        """Show today's PvE dailies"""
        embed = await self.daily_embed(["pve"])
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="wvw", aliases=["w", "WVW", "W"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_wvw(self, ctx):
        """Show today's WvW dailies"""
        embed = await self.daily_embed(["wvw"])
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="pvp", aliases=["p", "P", "PVP"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_pvp(self, ctx):
        """Show today's PvP dailies"""
        embed = await self.daily_embed(["pvp"])
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="fractals", aliases=["f", "F", "Fractals"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_fractals(self, ctx):
        """Show today's fractal dailies"""
        embed = await self.daily_embed(["fractals"])
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="psna")
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_psna(self, ctx):
        """Show today's Pact Supply Network Agent locations"""
        embed = await self.daily_embed(["psna"])
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @daily.command(name="all", aliases=["A", "a"])
    @commands.cooldown(1, 2, BucketType.user)
    async def daily_all(self, ctx):
        """Show today's all dailies"""
        embed = await self.daily_embed(
            ["psna", "pve", "pvp", "wvw", "fractals"])
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    async def daily_embed(self, categories, *, doc=None):
        if not doc:
            doc = await self.bot.database.get_cog_config(self)
        embed = discord.Embed(title="Dailies", color=self.embed_color)
        dailies = doc["cache"]["dailies"]
        for category in categories:
            value = "\n".join(dailies[category])
            if category == "psna_later":
                category = "psna in 8 hours"
            embed.add_field(name=category.upper(), value=value, inline=False)
        return embed

    def get_psna(self, *, offset_days=0):
        offset = datetime.timedelta(hours=-8)
        tzone = datetime.timezone(offset)
        day = datetime.datetime.now(tzone).weekday()
        if day + offset_days > 6:
            offset_days = -6
        return self.gamedata["pact_supply"][day + offset_days]
