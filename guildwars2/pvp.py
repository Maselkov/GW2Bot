import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType

from .exceptions import APIError


class PvpMixin:
    @cog_ext.cog_subcommand(base="pvp",
                            name="stats",
                            base_description="PVP related commands")
    async def pvp_stats(self, ctx):
        """Information about your general pvp stats"""
        await ctx.defer()
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
        data = discord.Embed(colour=await self.get_embed_color(ctx))
        data.add_field(name="Rank", value=rank, inline=False)
        data.add_field(name="Total games played", value=totalgamesplayed)
        data.add_field(name="Total wins", value=totalwins)
        data.add_field(name="Total winratio",
                       value="{}%".format(totalwinratio))
        data.add_field(name="Ranked games played", value=rankedgamesplayed)
        data.add_field(name="Ranked wins", value=rankedwins)
        data.add_field(name="Ranked winratio",
                       value="{}%".format(rankedwinratio))
        data.set_author(name=doc["account_name"])
        data.set_thumbnail(url=ranks["icon"])
        await ctx.send(embed=data)

    @cog_ext.cog_subcommand(
        base="pvp",
        name="professions",
        base_description="PVP related commands",
        options=[{
            "name":
            "profession",
            "description":
            "Profession for profession specific statistics",
            "type":
            SlashCommandOptionType.STRING,
            "choices": [
                {
                    "value": "warrior",
                    "name": "Warrior"
                },
                {
                    "value": "guardian",
                    "name": "Guardian"
                },
                {
                    "value": "revenant",
                    "name": "Revenant"
                },
                {
                    "value": "thief",
                    "name": "Thief"
                },
                {
                    "value": "ranger",
                    "name": "Ranger"
                },
                {
                    "value": "engineer",
                    "name": "Engineer"
                },
                {
                    "value": "elementalist",
                    "name": "Elementalist"
                },
                {
                    "value": "necromancer",
                    "name": "Necromancer"
                },
                {
                    "value": "mesmer",
                    "name": "Mesmer"
                },
            ],
            "required":
            False,
        }])
    async def pvp_professions(self, ctx, profession=None):
        """Information about your pvp profession stats."""
        await ctx.defer()
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
            mostplayed = max(professionsformat,
                             key=lambda i: professionsformat[i]['total'])
            icon = self.gamedata["professions"][mostplayed]["icon"]
            mostplayedgames = professionsformat[mostplayed]["total"]
            highestwinrate = max(
                professionsformat,
                key=lambda i: professionsformat[i]["winratio"])
            highestwinrategames = professionsformat[highestwinrate]["winratio"]
            leastplayed = min(professionsformat,
                              key=lambda i: professionsformat[i]["total"])
            leastplayedgames = professionsformat[leastplayed]["total"]
            lowestestwinrate = min(
                professionsformat,
                key=lambda i: professionsformat[i]["winratio"])
            lowestwinrategames = professionsformat[lowestestwinrate][
                "winratio"]
            data = discord.Embed(description="Professions",
                                 color=await self.get_embed_color(ctx))
            data.set_thumbnail(url=icon)
            data.add_field(name="Most played profession",
                           value="{0}, with {1}".format(
                               mostplayed.capitalize(), mostplayedgames))
            data.add_field(name="Highest winrate profession",
                           value="{0}, with {1}%".format(
                               highestwinrate.capitalize(),
                               highestwinrategames))
            data.add_field(name="Least played profession",
                           value="{0}, with {1}".format(
                               leastplayed.capitalize(), leastplayedgames))
            data.add_field(name="Lowest winrate profession",
                           value="{0}, with {1}%".format(
                               lowestestwinrate.capitalize(),
                               lowestwinrategames))
            data.set_author(name=doc["account_name"])
            return await ctx.send(embed=data)
        wins = (results["professions"][profession]["wins"] +
                results["professions"][profession]["byes"])
        total = sum(results["professions"][profession].values())
        winratio = int((wins / total) * 100)
        color = self.gamedata["professions"][profession]["color"]
        color = int(color, 0)
        data = discord.Embed(description=f"Stats for {profession}",
                             colour=color)
        data.set_thumbnail(
            url=self.gamedata["professions"][profession]["icon"])
        data.add_field(name="Total games played", value="{0}".format(total))
        data.add_field(name="Wins", value="{0}".format(wins))
        data.add_field(name="Winratio", value="{0}%".format(winratio))
        data.set_author(name=doc["account_name"])
        await ctx.send(embed=data)
