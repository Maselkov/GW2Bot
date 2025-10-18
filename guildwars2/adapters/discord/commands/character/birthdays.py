from typing import Dict, List, Tuple

import datetime
import discord
from discord import app_commands
from .. import with_cog
from .....types import GuildWars2Cog

from .....utils.chat import embed_list_lines


@app_commands.command(
    name="birthdays", description="Days until each character's next birthday"
)
@with_cog()
async def character_birthdays(cog: GuildWars2Cog, interaction: discord.Interaction):
    await interaction.response.defer()

    def suffix(year: int) -> str:
        return {1: "st", 2: "nd", 3: "rd"}.get(year, "th")

    doc = await cog.fetch_key(  # type: ignore[attr-defined]
        interaction.user, ["characters"]
    )
    characters = await cog.container.characters_service.get_all_characters(
        key=doc["key"]
    )
    fields: Dict[int, List[Tuple[str, int]]] = {}
    for character in characters:
        created_str = character.get("created", "1970-01-01T00:00:00Z").split("T", 1)[0]
        try:
            created_dt = datetime.datetime.strptime(created_str, "%Y-%m-%d")
        except ValueError:
            # Fallback to full timestamp if date-only parse fails
            try:
                created_dt = datetime.datetime.strptime(
                    character.get("created", "1970-01-01T00:00:00Z"),
                    "%Y-%m-%dT%H:%M:%SZ",
                )
            except ValueError:
                created_dt = datetime.datetime.utcnow()
        age = datetime.datetime.utcnow() - created_dt
        days = age.days
        floor = days // 365
        days_left = 365 - (days - (365 * floor))
        next_bd = floor + 1
        fields.setdefault(next_bd, [])
        prof = await cog.container.characters_service.get_profession_by_character(
            character, cog.gamedata
        )
        label = f"{cog.get_emoji(interaction, prof['name'])} {character.get('name')}"
        fields[next_bd].append((label, days_left))

    embed = discord.Embed(
        title="Days until...", colour=await cog.get_embed_color(interaction)
    )
    embed.set_author(
        name=doc["account_name"], icon_url=interaction.user.display_avatar.url
    )
    for k, v in sorted(fields.items(), reverse=True, key=lambda item: item[0]):
        lines = [
            f"{name}: **{days}**" for name, days in sorted(v, key=lambda pair: pair[1])
        ]
        embed = embed_list_lines(embed, lines, f"{k}{suffix(k)} Birthday")
    await interaction.followup.send(embed=embed)
