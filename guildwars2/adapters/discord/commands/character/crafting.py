import discord
from discord import app_commands
from .. import with_cog
from .....types import GuildWars2Cog


@app_commands.command(
    name="crafting", description="Displays your characters' crafting levels"
)
@with_cog()
async def character_crafting(cog: GuildWars2Cog, interaction: discord.Interaction):
    await interaction.response.defer()

    endpoint = "characters?page=0&page_size=200"
    doc = await cog.fetch_key(  # type: ignore[attr-defined]
        interaction.user, ["characters"]
    )
    characters = await cog.call_api(  # type: ignore[attr-defined]
        endpoint, key=doc["key"]
    )
    data = discord.Embed(
        description="Crafting overview", colour=await cog.get_embed_color(interaction)
    )
    data.set_author(
        name=doc["account_name"], icon_url=interaction.user.display_avatar.url
    )
    counter = 0
    for character in characters:
        if counter == 25:
            break
        craft_list = cog.container.characters_service.get_crafting(character)
        if craft_list:
            data.add_field(name=character["name"], value="\n".join(craft_list))
            counter += 1
    await interaction.followup.send(embed=data)
