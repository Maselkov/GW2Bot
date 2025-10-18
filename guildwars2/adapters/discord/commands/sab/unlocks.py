import discord
from discord import app_commands
from .. import with_cog
from .....types import GuildWars2Cog

from .....exceptions import APIError, APINotFound
from ..character.autocomplete import character_autocomplete


@app_commands.command(name="unlocks", description="Missing SAB unlocks for a character")
@app_commands.autocomplete(character=character_autocomplete)
@with_cog()
async def sab_unlocks(
    cog: GuildWars2Cog, interaction: discord.Interaction, character: str
):
    await interaction.response.defer()

    def readable(_id: str) -> str:
        return _id.replace("_", " ").title()

    scopes = ["characters", "progression"]
    character_q = character.title().replace(" ", "%20")
    endpoint = f"characters/{character_q}/sab"
    try:
        results = await cog.call_api(endpoint, interaction.user, scopes)
    except APINotFound:
        return await interaction.followup.send("Invalid character name")
    except APIError:
        raise
    unlocked = [u["name"] for u in results.get("unlocks", [])]
    missing = [
        readable(u)
        for u in cog.gamedata.get("sab", {}).get("unlocks", [])
        if u not in unlocked
    ]
    if missing:
        return await interaction.followup.send(
            "This character is missing the following SAB upgrades:\n"
            + "```fix\n{}\n```".format("\n".join(missing))
        )
    await interaction.followup.send(
        "You have unlocked all the upgrades on this character! Congratulations!"
    )
