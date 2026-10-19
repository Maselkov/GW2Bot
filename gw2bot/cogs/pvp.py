"""PvP commands: /pvp stats and /pvp professions."""
import discord
from discord import app_commands
from discord.app_commands import Choice

from .base import GW2Cog

PROFESSIONS = [
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


def win_ratio(record):
    """(wins, games, win %) for a games record ({wins, losses, desertions,
    byes, forfeits}). Byes count as wins; the % is rounded down, and 0 with
    no games."""
    wins = record["wins"] + record["byes"]
    total = sum(record.values())
    return wins, total, int((wins / total) * 100) if total else 0


def overall(stats):
    """Rank and totals from /v2/pvp/stats."""
    total_wins, total_games, total_ratio = win_ratio(stats["aggregate"])
    ranked_wins, ranked_games, ranked_ratio = win_ratio(stats["ladders"]["ranked"])
    return {
        "rank": stats["pvp_rank"] + stats["pvp_rank_rollovers"],
        # /v2/pvp/ranks ids are bands of 10 ranks
        "rank_id": stats["pvp_rank"] // 10 + 1,
        "games": total_games,
        "wins": total_wins,
        "ratio": total_ratio,
        "ranked_games": ranked_games,
        "ranked_wins": ranked_wins,
        "ranked_ratio": ranked_ratio,
    }


def profession_records(stats, professions):
    """{profession: (wins, games, win %)} for the played ones among
    `professions`, in that order."""
    return {
        profession: win_ratio(stats["professions"][profession])
        for profession in professions
        if profession in stats["professions"]
    }


def extremes(records):
    """The most and least played professions and the highest and lowest win
    rates, as (profession, value) pairs."""
    def by(index):
        return lambda profession: records[profession][index]

    most_played = max(records, key=by(1))
    highest = max(records, key=by(2))
    least_played = min(records, key=by(1))
    lowest = min(records, key=by(2))
    return {
        "most_played": (most_played, records[most_played][1]),
        "highest_ratio": (highest, records[highest][2]),
        "least_played": (least_played, records[least_played][1]),
        "lowest_ratio": (lowest, records[lowest][2]),
    }


class Pvp(GW2Cog):
    pvp_group = app_commands.Group(name="pvp",
                                   description="PvP related commands")

    @pvp_group.command(name="stats")
    async def pvp_stats(self, interaction: discord.Interaction):
        """Information about your general pvp stats"""
        await interaction.response.defer()
        doc = await self.fetch_key(interaction.user, ["pvp"])
        results = await self.call_api("pvp/stats", key=doc["key"])
        summary = overall(results)
        ranks = await self.call_api("pvp/ranks/{0}".format(summary["rank_id"]))
        embed = discord.Embed(colour=await self.get_embed_color(interaction))
        embed.add_field(name="Rank", value=summary["rank"], inline=False)
        embed.add_field(name="Total games played", value=summary["games"])
        embed.add_field(name="Total wins", value=summary["wins"])
        embed.add_field(name="Total winratio", value="{}%".format(summary["ratio"]))
        embed.add_field(name="Ranked games played", value=summary["ranked_games"])
        embed.add_field(name="Ranked wins", value=summary["ranked_wins"])
        embed.add_field(name="Ranked winratio", value="{}%".format(summary["ranked_ratio"]))
        embed.set_author(name=doc["account_name"])
        embed.set_thumbnail(url=ranks["icon"])
        await interaction.followup.send(embed=embed)

    @pvp_group.command(name="professions")
    @app_commands.describe(
        profession="Select a profession to view specific statistics")
    @app_commands.choices(profession=[
        Choice(name=p.title(), value=p) for p in PROFESSIONS
    ])
    async def pvp_professions(self,
                              interaction: discord.Interaction,
                              profession: str = None):
        """Information about your pvp profession stats."""
        await interaction.response.defer()
        doc = await self.fetch_key(interaction.user, ["pvp"])
        results = await self.call_api("pvp/stats", key=doc["key"])
        if not profession:
            records = profession_records(results, self.gamedata["professions"].keys())
            top = extremes(records)
            most_played, most_played_games = top["most_played"]
            data = discord.Embed(description="Professions",
                                 color=await self.get_embed_color(interaction))
            data.set_thumbnail(url=self.gamedata["professions"][most_played]["icon"])
            data.add_field(name="Most played profession",
                           value="{0}, with {1}".format(most_played.capitalize(), most_played_games))
            data.add_field(name="Highest winrate profession",
                           value="{0}, with {1}%".format(top["highest_ratio"][0].capitalize(),
                                                         top["highest_ratio"][1]))
            data.add_field(name="Least played profession",
                           value="{0}, with {1}".format(top["least_played"][0].capitalize(),
                                                       top["least_played"][1]))
            data.add_field(name="Lowest winrate profession",
                           value="{0}, with {1}%".format(top["lowest_ratio"][0].capitalize(),
                                                         top["lowest_ratio"][1]))
            data.set_author(name=doc["account_name"])
            return await interaction.followup.send(embed=data)
        wins, total, winratio = win_ratio(results["professions"][profession])
        color = int(self.gamedata["professions"][profession]["color"], 0)
        data = discord.Embed(description=f"Stats for {profession}",
                             colour=color)
        data.set_thumbnail(
            url=self.gamedata["professions"][profession]["icon"])
        data.add_field(name="Total games played", value="{0}".format(total))
        data.add_field(name="Wins", value="{0}".format(wins))
        data.add_field(name="Winratio", value="{0}%".format(winratio))
        data.set_author(name=doc["account_name"])
        await interaction.followup.send(embed=data)


async def setup(bot):
    await bot.add_cog(Pvp(bot))
