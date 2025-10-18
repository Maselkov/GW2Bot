import discord
from discord import app_commands
from .. import with_cog

from .....exceptions import APIError, APINotFound
from .autocomplete import character_autocomplete
from .....types import GuildWars2Cog


# Group attachment handled by package-level group discovery
@app_commands.command(name="info", description="Info about the given character")
@app_commands.autocomplete(character=character_autocomplete)
@app_commands.describe(character="Name of your character")
@with_cog()
async def character_info(
    cog: GuildWars2Cog, interaction: discord.Interaction, character: str
):
    """Info about the given character"""
    await interaction.response.defer()
    # Acquire key with minimal required scope
    try:
        key_doc = await cog.container.keys_service.get_key_for_user(
            interaction.user, required_scopes=["characters"], cog=cog
        )
    except Exception:
        return await interaction.followup.send(
            "No API key with 'characters' permission found. Add a key with /key add."
        )
    # Fetch character via service; fallback to public if needed
    try:
        results = await cog.container.characters_service.get_character_by_key(
            name=character, key=key_doc["key"]
        )
    except APINotFound:
        # Check if character is public and fetch with owner's key
        pub = await cog.container.repo.get_public_character(character.title())
        if not pub:
            return await interaction.followup.send("Invalid character name")
        try:
            owner = await cog.bot.fetch_user(pub["owner"])  # type: ignore[index]
            owner_key = await cog.container.keys_service.get_key_for_user(
                owner, required_scopes=["characters"], cog=cog
            )
            results = await cog.container.characters_service.get_character_by_key(
                name=character, key=owner_key["key"]
            )
        except Exception:
            return await interaction.followup.send("Invalid character name")
    except APIError:
        raise
    age = cog.container.characters_service.format_age(results["age"])
    created = results["created"].split("T", 1)[0]
    deaths = results["deaths"]
    deathsperhour = round(deaths / (results["age"] / 3600), 1)
    if "title" in results:
        title = await cog.container.characters_service.get_title(results["title"])
    else:
        title = None
    profession = await cog.container.characters_service.get_profession_by_character(
        results, cog.gamedata
    )
    gender = results["gender"]
    race = results["race"].lower()
    guild = results.get("guild")

    embed = discord.Embed(description=title, colour=profession["color"])
    embed.set_thumbnail(url=profession["icon"])
    embed.add_field(name="Created at", value=created)
    embed.add_field(name="Played for", value=age)
    if guild is not None:
        endpoint = f"guild/{results['guild']}"
        guild_doc = await cog.call_api(endpoint)
        gname = guild_doc["name"]
        gtag = guild_doc["tag"]
        embed.add_field(name="Guild", value=f"[{gtag}] {gname}")
    embed.add_field(name="Deaths", value=deaths)
    embed.add_field(name="Deaths per hour", value=str(deathsperhour), inline=False)
    craft_list = cog.container.characters_service.get_crafting(results)
    if craft_list:
        embed.add_field(name="Crafting", value="\n".join(craft_list))
    embed.set_author(name=character)
    embed.set_footer(text=f"A {gender.lower()} {race} {profession['name'].lower()}")
    await interaction.followup.send(embed=embed)
