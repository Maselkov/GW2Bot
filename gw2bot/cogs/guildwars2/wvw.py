import discord
from discord import app_commands
from discord.app_commands import Choice

from .utils.db import prepare_search


class WvwMixin:

    wvw_group = app_commands.Group(name="wvw",
                                   description="WvW related commands")

    async def world_autocomplete(self, interaction: discord.Interaction,
                                 current: str):
        if not current:
            return []
        current = current.lower()
        query = prepare_search(current)
        query = {"name": query}
        items = await self.db.worlds.find(query).to_list(25)
        return [Choice(name=it["name"], value=str(it["_id"])) for it in items]

    @wvw_group.command(name="info")
    @app_commands.describe(
        world="World name. Leave blank to use your account's world")
    @app_commands.autocomplete(world=world_autocomplete)
    async def wvw_info(self,
                       interaction: discord.Interaction,
                       *,
                       world: str = None):
        """Info about a world. Defaults to account's world"""
        user = interaction.user
        await interaction.response.defer()
        if not world:
            endpoint = "account"
            results = await self.call_api(endpoint, user)
            wid = results["world"]
        else:
            wid = world
        if not wid:
            return await interaction.followup.send("Invalid world name")
        endpoints = [
            "wvw/matches?world={0}".format(wid), "worlds?id={0}".format(wid)
        ]
        matches, worldinfo = await self.call_multiple(endpoints)
        linked_worlds = []
        worldcolor = "green"
        for key, value in matches["all_worlds"].items():
            if wid in value:
                worldcolor = key
                value.remove(wid)
                linked_worlds = value
                break
        if worldcolor == "red":
            color = discord.Colour.red()
        elif worldcolor == "green":
            color = discord.Colour.green()
        else:
            color = discord.Colour.blue()
        linked_worlds = [await self.get_world_name(w) for w in linked_worlds]
        score = matches["scores"][worldcolor]
        ppt = 0
        victoryp = matches["victory_points"][worldcolor]
        for m in matches["maps"]:
            for objective in m["objectives"]:
                if objective["owner"].lower() == worldcolor:
                    ppt += objective["points_tick"]
        kills = matches["kills"][worldcolor]
        deaths = matches["deaths"][worldcolor]
        kd = round((kills / deaths), 2)
        data = discord.Embed(description="Performance", colour=color)
        data.add_field(name="Score", value=score)
        data.add_field(name="Points per tick", value=ppt)
        data.add_field(name="Victory Points", value=victoryp)
        data.add_field(name="K/D ratio", value=str(kd), inline=False)
        if linked_worlds:
            data.add_field(name="Linked with", value=", ".join(linked_worlds))
        data.set_author(name=worldinfo["name"])
        await interaction.followup.send(embed=data)
