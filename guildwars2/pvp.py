import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError


class PvpMixin:
    @commands.group()
    async def pvp(self, ctx):
        """PvP related commands.
        """
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @pvp.command(name="stats")
    @commands.cooldown(1, 20, BucketType.user)
    async def pvp_stats(self, ctx):
        """Information about your general pvp stats

        Required permissions: pvp
        """
        try:
            doc = await self.fetch_key(ctx.author, ["pvp"])
            results = await self.call_api("pvp/stats", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        rank = results["pvp_rank"] + results["pvp_rank_rollovers"]
        totalgamesplayed = sum(results["aggregate"].values())
        totalwins = results["aggregate"]["wins"] + results["aggregate"]["byes"]
        if totalgamesplayed != 0:
            totalwinratio = int((totalwins / totalgamesplayed) * 100)
        else:
            totalwinratio = 0
        rankedgamesplayed = sum(results["ladders"]["ranked"].values())
        rankedwins = results["ladders"]["ranked"]["wins"] + \
            results["ladders"]["ranked"]["byes"]
        if rankedgamesplayed != 0:
            rankedwinratio = int((rankedwins / rankedgamesplayed) * 100)
        else:
            rankedwinratio = 0
        rank_id = results["pvp_rank"] // 10 + 1
        try:
            ranks = await self.call_api("pvp/ranks/{0}".format(rank_id))
        except APIError as e:
            await self.error_handler(ctx, e)
            return
        data = discord.Embed(olour=self.embed_color)
        data.add_field(name="Rank", value=rank, inline=False)
        data.add_field(name="Total games played", value=totalgamesplayed)
        data.add_field(name="Total wins", value=totalwins)
        data.add_field(
            name="Total winratio", value="{}%".format(totalwinratio))
        data.add_field(name="Ranked games played", value=rankedgamesplayed)
        data.add_field(name="Ranked wins", value=rankedwins)
        data.add_field(
            name="Ranked winratio", value="{}%".format(rankedwinratio))
        data.set_author(name=doc["account_name"])
        data.set_thumbnail(url=ranks["icon"])
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @pvp.command(name="professions")
    @commands.cooldown(1, 5, BucketType.user)
    async def pvp_professions(self, ctx, *, profession: str=None):
        """Information about your pvp profession stats.
        If no profession is given, defaults to general profession stats.
        Example! $pvp professions mesmer

        Required permissions: pvp
        """
        try:
            doc = await self.fetch_key(ctx.author, ["pvp"])
            results = await self.call_api("pvp/stats", key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        professions = self.gamedata["professions"].keys()
        professionsformat = {}
        if not profession:
            for profession in professions:
                if profession in results["professions"]:
                    wins = (results["professions"][profession]["wins"] +
                            results["professions"][profession]["byes"])
                    total = sum(results["professions"][profession].values())
                    winratio = int((wins / total) * 100)
                    professionsformat[profession] = {
                        "wins": wins,
                        "total": total,
                        "winratio": winratio
                    }
            mostplayed = max(
                professionsformat, key=lambda i: professionsformat[i]['total'])
            icon = self.gamedata["professions"][mostplayed]["icon"]
            mostplayedgames = professionsformat[mostplayed]["total"]
            highestwinrate = max(
                professionsformat,
                key=lambda i: professionsformat[i]["winratio"])
            highestwinrategames = professionsformat[highestwinrate]["winratio"]
            leastplayed = min(
                professionsformat, key=lambda i: professionsformat[i]["total"])
            leastplayedgames = professionsformat[leastplayed]["total"]
            lowestestwinrate = min(
                professionsformat,
                key=lambda i: professionsformat[i]["winratio"])
            lowestwinrategames = professionsformat[lowestestwinrate][
                "winratio"]
            data = discord.Embed(
                description="Professions", color=self.embed_color)
            data.set_thumbnail(url=icon)
            data.add_field(
                name="Most played profession",
                value="{0}, with {1}".format(mostplayed.capitalize(),
                                             mostplayedgames))
            data.add_field(
                name="Highest winrate profession",
                value="{0}, with {1}%".format(highestwinrate.capitalize(),
                                              highestwinrategames))
            data.add_field(
                name="Least played profession",
                value="{0}, with {1}".format(leastplayed.capitalize(),
                                             leastplayedgames))
            data.add_field(
                name="Lowest winrate profession",
                value="{0}, with {1}%".format(lowestestwinrate.capitalize(),
                                              lowestwinrategames))
            data.set_author(name=doc["account_name"])
            data.set_footer(
                text="PROTIP: Use $pvp professions <profession> for "
                "more detailed stats")
            try:
                await ctx.send(embed=data)
            except discord.HTTPException:
                await ctx.send("Need permission to embed links")
        elif profession.lower() not in self.gamedata["professions"]:
            await ctx.send("Invalid profession")
        elif profession.lower() not in results["professions"]:
            await ctx.send("You haven't played that profession!")
        else:
            prof = profession.lower()
            wins = results["professions"][prof]["wins"] + \
                results["professions"][prof]["byes"]
            total = sum(results["professions"][prof].values())
            winratio = int((wins / total) * 100)
            color = self.gamedata["professions"][prof]["color"]
            color = int(color, 0)
            data = discord.Embed(
                description="Stats for {0}".format(prof), colour=color)
            data.set_thumbnail(url=self.gamedata["professions"][prof]["icon"])
            data.add_field(
                name="Total games played", value="{0}".format(total))
            data.add_field(name="Wins", value="{0}".format(wins))
            data.add_field(name="Winratio", value="{0}%".format(winratio))
            data.set_author(name=doc["account_name"])
            try:
                await ctx.send(embed=data)
            except discord.Forbidden:
                await ctx.send("Need permission to embed links")
