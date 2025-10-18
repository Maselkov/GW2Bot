from typing import Dict, List

import discord
from discord import app_commands
from .. import with_cog
from .....types import GuildWars2Cog

from .....exceptions import APIError, APINotFound
from ..character.autocomplete import character_autocomplete


@app_commands.command(name="zones", description="Missing SAB zones for a character")
@app_commands.autocomplete(character=character_autocomplete)
@with_cog()
async def sab_zones(
    cog: GuildWars2Cog, interaction: discord.Interaction, character: str
):
    await interaction.response.defer()

    def missing_zones(zones: List[Dict[str, str]]):
        modes = ["infantile", "normal", "tribulation"]
        worlds = (1, 2)
        number_of_zones = 3
        [z.pop("id", None) for z in zones]
        missing: List[str] = []
        for world in worlds:
            for mode in modes:
                for zone in range(1, number_of_zones + 1):
                    zone_dict = {"world": world, "zone": zone, "mode": mode}
                    if zone_dict not in zones:
                        missing.append(f"W{world}Z{zone} {mode.title()} mode")
        return missing

    scopes = ["characters", "progression"]
    character_q = character.title().replace(" ", "%20")
    endpoint = f"characters/{character_q}/sab"
    try:
        results = await cog.call_api(endpoint, interaction.user, scopes)
    except APINotFound:
        return await interaction.followup.send("Invalid character name")
    except APIError:
        raise
    missing = missing_zones(results.get("zones", []))
    if missing:
        return await interaction.followup.send(
            "This character is missing the following SAB zones:\n"
            + "```fix\n{}\n```".format("\n".join(missing))
        )
    await interaction.followup.send(
        "You have unlocked all zones on this character! Congratulations!"
    )
