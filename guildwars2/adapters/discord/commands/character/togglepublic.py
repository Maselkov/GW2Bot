from typing import List

import discord
from discord import app_commands
from .. import with_cog
from .....types import GuildWars2Cog


@app_commands.command(
    name="togglepublic",
    description="Toggle your character's (or all) public status",
)
@app_commands.describe(character_or_all="Character name or 'All'")
@with_cog()
async def character_togglepublic(
    cog: GuildWars2Cog, interaction: discord.Interaction, *, character_or_all: str
):
    """Toggle your character's (or all of them) status to public

    Public characters can have their gear and build checked by anyone.
    The rest is still private.
    """
    await interaction.response.defer()
    character = character_or_all.title()
    key = await cog.fetch_key(  # type: ignore[attr-defined]
        interaction.user, ["characters"]
    )
    results = await cog.call_api(  # type: ignore[attr-defined]
        "characters", key=key["key"]
    )
    if character not in results and character != "All":
        return await interaction.followup.send("Invalid character name")
    characters: List[str] = [character] if character != "All" else results
    output: List[str] = []
    for char in characters:
        doc = await cog.db.characters.find_one({"name": char})
        if doc:
            await cog.db.characters.delete_one({"name": char})
            output.append(char + " is now private")
        else:
            await cog.db.characters.insert_one(
                {
                    "name": char,
                    "owner": interaction.user.id,
                    "owner_acc_name": key["account_name"],
                }
            )
            output.append(char + " is now public")
    await interaction.followup.send(
        "Character status successfully changed. Anyone can check public characters "
        "gear and build - the rest is still private. To make a character private "
        "again, run the command again."
    )
    if character == "All":
        await interaction.user.send("\n".join(output))
