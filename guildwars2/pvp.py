import discord
from discord import app_commands
from discord.app_commands import Choice


class PvpMixin:
    pvp_group = app_commands.Group(name="pvp",
                                   description="PvP related commands")

    @pvp_group.command(name="stats")
    async def pvp_stats(self, interaction: discord.Interaction):
        """Information about your general pvp stats"""
        await interaction.response.defer()
        doc = await self.fetch_key(interaction.user, ["pvp"])
        results = await self.call_api("pvp/stats", key=doc["key"])
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
        ranks = await self.call_api("pvp/ranks/{0}".format(rank_id))
        embed = discord.Embed(colour=await self.get_embed_color(interaction))
        embed.add_field(name="Rank", value=rank, inline=False)
        embed.add_field(name="Total games played", value=totalgamesplayed)
        embed.add_field(name="Total wins", value=totalwins)
        embed.add_field(name="Total winratio",
                        value="{}%".format(totalwinratio))
        embed.add_field(name="Ranked games played", value=rankedgamesplayed)
        embed.add_field(name="Ranked wins", value=rankedwins)
        embed.add_field(name="Ranked winratio",
                        value="{}%".format(rankedwinratio))
        embed.set_author(name=doc["account_name"])
        embed.set_thumbnail(url=ranks["icon"])
        await interaction.followup.send(embed=embed)

    @pvp_group.command(name="professions")
    @app_commands.describe(profession="Profession for profession "
                           "specific statistics. Leave blank for total stats.")
    @app_commands.choices(profession=[
        Choice(name=p.title(), value=p) for p in [
            "warrior",
            "guardian",
            "revenant",
            "thief",
            "ranger",
            "engineer",
            "elementalist",
            "necromancer",
            "mesmer",
        ]
    ])
    async def pvp_professions(self,
                              interaction: discord.Interaction,
                              profession: str = None):
        """Information about your pvp profession stats."""
        await interaction.response.defer()
        doc = await self.fetch_key(interaction.user, ["pvp"])
        results = await self.call_api("pvp/stats", key=doc["key"])
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
                                 color=await self.get_embed_color(interaction))
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
            return await interaction.followup.send(embed=data)
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
        await interaction.followup.send(embed=data)
