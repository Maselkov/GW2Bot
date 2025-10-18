from typing import List

import datetime
import discord
from discord import app_commands
from .. import with_cog
from .....types import GuildWars2Cog

from .....utils.chat import embed_list_lines


@app_commands.command(name="list", description="Lists all your characters")
@app_commands.describe(info="Additional info and sort key")
@app_commands.choices(
    info=[
        app_commands.Choice(name="Time played", value="age"),
        app_commands.Choice(name="Age", value="created"),
        app_commands.Choice(name="Profession", value="profession"),
    ]
)
@with_cog()
async def character_list(
    cog: GuildWars2Cog, interaction: discord.Interaction, info: str = "name"
):
    await interaction.response.defer()

    def get_sort_key():
        if info == "profession":
            return lambda k: (k.profession, k.name)
        if info == "age":
            return lambda k: (-k.age, k.name)
        if info == "created":
            return lambda k: (
                -(datetime.datetime.utcnow() - k.created).total_seconds(),
                k.name,
            )
        return lambda k: k.name

    def extra_info(char):
        if info == "age":
            return ": " + cog.container.characters_service.format_age(
                char.age, short=True
            )
        if info == "created":
            return f": <t:{int(char.created.timestamp())}:f>"
        is_80 = char.level == 80
        return "" + (f" (Level {char.level})" if not is_80 else "")

    user = interaction.user
    # Use service to fetch characters for this user's key
    doc = await cog.fetch_key(user, ["characters"])  # type: ignore[attr-defined]
    characters = await cog.container.characters_service.get_all_characters(
        key=doc["key"]
    )
    embed = discord.Embed(
        title="Your characters", colour=await cog.get_embed_color(interaction)
    )
    embed.set_author(name=doc["account_name"], icon_url=user.display_avatar.url)
    output: List[str] = []

    def sort_key_dict(ch: dict):
        if info == "profession":
            return (ch.get("profession", ""), ch.get("name", ""))
        if info == "age":
            return (-(ch.get("age", 0)), ch.get("name", ""))
        if info == "created":
            try:
                created_dt = datetime.datetime.strptime(
                    ch.get("created", "1970-01-01T00:00:00Z"), "%Y-%m-%dT%H:%M:%SZ"
                )
                seconds = (datetime.datetime.utcnow() - created_dt).total_seconds()
            except Exception:
                seconds = 0
            return (-seconds, ch.get("name", ""))
        return ch.get("name", "")

    for character in sorted(characters, key=sort_key_dict):
        prof = await cog.container.characters_service.get_profession_by_character(
            character, cog.gamedata
        )
        emoji = cog.get_emoji(
            interaction, prof["name"], fallback=True, fallback_fmt="**({})** "
        )

        def extra_info_dict(ch: dict):
            if info == "age":
                return ": " + cog.container.characters_service.format_age(
                    ch.get("age", 0), short=True
                )
            if info == "created":
                try:
                    created_dt = datetime.datetime.strptime(
                        ch.get("created", "1970-01-01T00:00:00Z"), "%Y-%m-%dT%H:%M:%SZ"
                    )
                    return f": <t:{int(created_dt.timestamp())}:f>"
                except Exception:
                    return ""
            is_80 = ch.get("level", 0) == 80
            lvl = ch.get("level", 0)
            return "" + (f" (Level {lvl})" if not is_80 else "")

        output.append(f"{emoji}**{character.get('name')}**{extra_info_dict(character)}")
    info_label = {"created": "date of creation", "age": "time played"}.get(info, info)
    embed = embed_list_lines(embed, output, "List")
    embed.description = "Sorted by " + info_label
    await interaction.followup.send(embed=embed)
