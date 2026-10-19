"""WvW commands: /wvw info."""
import discord
from discord import app_commands
from discord.app_commands import Choice

from .base import GW2Cog

# First /v2/account schema with the `wvw` object (team_id, rank)
WVW_ACCOUNT_SCHEMA = "2024-07-20T01:00:00.000Z"


def match_summary(match, team_id):
    """The team's side of a /v2/wvw/matches response, or None if it isn't in it.

    all_worlds lists each side's teams (11xxx NA, 12xxx EU) next to the world
    ids from before the World Restructuring.
    """
    color = next(
        (c for c, ids in match["all_worlds"].items() if team_id in ids), None)
    if not color:
        return None
    ppt = sum(objective["points_tick"] for m in match["maps"]
              for objective in m["objectives"]
              if objective["owner"].lower() == color)
    return {
        "color": color,
        "score": match["scores"][color],
        "victory_points": match["victory_points"][color],
        "points_per_tick": ppt,
        "kills": match["kills"][color],
        "deaths": match["deaths"][color],
        "teams": {
            c: [i for i in ids if i >= 10000]
            for c, ids in match["all_worlds"].items()
        },
    }


def team_name(gamedata, team_id):
    return gamedata["wvw_teams"].get(str(team_id), f"Team {team_id}")


def team_region(team_id):
    return "NA" if str(team_id).startswith("11") else "EU"


def find_team(gamedata, team):
    """Team id from an autocomplete value or a typed team name."""
    if team.isdigit():
        return int(team)
    for team_id, name in gamedata["wvw_teams"].items():
        if name.lower() == team.strip().lower():
            return int(team_id)
    return None


class Wvw(GW2Cog):

    wvw_group = app_commands.Group(name="wvw",
                                   description="WvW related commands")

    async def team_autocomplete(self, interaction: discord.Interaction,
                                current: str):
        current = current.lower()
        return [
            Choice(name=f"{name} ({team_region(team_id)})", value=team_id)
            for team_id, name in self.gamedata["wvw_teams"].items()
            if current in name.lower()
        ][:25]

    @wvw_group.command(name="info")
    @app_commands.describe(
        team="WvW team name. Leave blank to use your account's team")
    @app_commands.autocomplete(team=team_autocomplete)
    async def wvw_info(self,
                       interaction: discord.Interaction,
                       *,
                       team: str = None):
        """Info about a WvW team's matchup. Defaults to your account's team"""
        user = interaction.user
        await interaction.response.defer()
        if not team:
            results = await self.call_api("account",
                                          user, ["account"],
                                          schema_string=WVW_ACCOUNT_SCHEMA)
            team_id = results.get("wvw", {}).get("team_id")
            if not team_id:
                return await interaction.followup.send(
                    "Your account isn't on a WvW team right now. Use the "
                    "`team` option to look up a team.")
        else:
            team_id = find_team(self.gamedata, team)
            if not team_id:
                return await interaction.followup.send("Invalid team name")
        match = await self.call_api(f"wvw/matches?world={team_id}")
        summary = match_summary(match, team_id)
        if not summary:
            return await interaction.followup.send(
                "That team isn't in a match right now.")
        color = summary["color"]
        if color == "red":
            colour = discord.Colour.red()
        elif color == "green":
            colour = discord.Colour.green()
        else:
            colour = discord.Colour.blue()
        kd = round(summary["kills"] / max(summary["deaths"], 1), 2)
        data = discord.Embed(description="Performance", colour=colour)
        data.add_field(name="Score", value=summary["score"])
        data.add_field(name="Points per tick", value=summary["points_per_tick"])
        data.add_field(name="Victory Points", value=summary["victory_points"])
        data.add_field(name="K/D ratio", value=str(kd), inline=False)
        matchup = []
        for side in "red", "blue", "green":
            names = ", ".join(
                team_name(self.gamedata, t) for t in summary["teams"].get(side, []))
            matchup.append(f"{side.title()}: {names or '-'}")
        data.add_field(name="Matchup", value="\n".join(matchup), inline=False)
        data.set_author(name=team_name(self.gamedata, team_id))
        await interaction.followup.send(embed=data)


async def setup(bot):
    await bot.add_cog(Wvw(bot))
