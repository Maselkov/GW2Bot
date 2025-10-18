import discord
from discord import app_commands
from .. import with_cog

from .....exceptions import APIError, APINotFound
from .autocomplete import character_autocomplete
from .....types import GuildWars2Cog


@app_commands.command(
    name="fashion", description="Displays the fashion wars of a character"
)
@app_commands.autocomplete(character=character_autocomplete)
@app_commands.describe(character="Name of your character")
@with_cog()
async def character_fashion(
    cog: GuildWars2Cog, interaction: discord.Interaction, character: str
):
    await interaction.response.defer()

    # Fetch character via API using the user's key
    try:
        key_doc = await cog.container.keys_service.get_key_for_user(
            interaction.user, required_scopes=["characters"], cog=cog
        )
        results = await cog.container.characters_service.get_character_by_key(
            name=character, key=key_doc["key"]
        )
    except APINotFound:
        return await interaction.followup.send("Invalid character name")
    except APIError:
        raise

    # Build gear info from equipment and DB
    eq = [
        x
        for x in results.get("equipment", [])
        if str(x.get("location", "")).startswith("Equipped")
    ]
    pieces = [
        "Helm",
        "Shoulders",
        "Coat",
        "Gloves",
        "Leggings",
        "Boots",
        "Backpack",
        "WeaponA1",
        "WeaponA2",
        "WeaponB1",
        "WeaponB2",
    ]
    gear = {piece: {} for piece in pieces}

    profession = await cog.container.characters_service.get_profession_by_character(
        results, cog.gamedata
    )
    level = results.get("level", 0)

    for item in eq:
        slot = item.get("slot")
        if slot not in pieces:
            continue
        dye_ids = item.get("dyes", []) or []
        dyes = []
        for dye in dye_ids:
            if dye:
                doc = await cog.db.colors.find_one({"_id": dye})
                if doc:
                    dyes.append(doc.get("name"))
                    continue
            dyes.append(None)
        gear[slot]["dyes"] = dyes
        skin = item.get("skin")
        if skin:
            doc = await cog.db.skins.find_one({"_id": skin})
            if doc:
                gear[slot]["name"] = doc.get("name")
                continue
        doc = await cog.db.items.find_one({"_id": item.get("id")})
        if doc:
            gear[slot]["name"] = doc.get("name")

    embed = discord.Embed(description="Fashion", colour=profession["color"])
    for piece in pieces:
        info = gear.get(piece) or {}
        if not info:
            continue
        value_lines = []
        for i, dye in enumerate(info.get("dyes", []), start=1):
            if dye:
                value_lines.append(f"Channel {i}: {dye}")
        value = "\n".join(value_lines) or "\u200b"
        embed.add_field(name=info.get("name", piece), value=value, inline=False)
    embed.set_author(name=character)
    embed.set_footer(
        text=f"A level {level} {profession['name'].lower()}",
        icon_url=profession["icon"],
    )
    await interaction.followup.send(embed=embed)
