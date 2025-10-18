from itertools import chain

import discord
from discord import app_commands

from .. import with_cog
from .....exceptions import APIError, APINotFound


@app_commands.command(
    name="kp",
    description="Shows completed raids, fractals, strikes, and important challenges",
)
@with_cog()
async def account_kp(cog, interaction: discord.Interaction):
    await interaction.response.defer()
    user = interaction.user
    scopes = ["progression"]
    areas = cog.gamedata["killproofs"]["areas"]
    achievement_ids = [
        (
            [x["id"]]
            if x["type"] in ("single_achievement", "progressed_achievement")
            else x["ids"]
        )
        for x in chain.from_iterable([area["encounters"] for area in areas])
    ]
    achievement_ids = [str(x) for x in chain.from_iterable(achievement_ids)]
    try:
        doc = await cog.fetch_key(user, scopes)  # type: ignore[attr-defined]
        endpoint = "account/achievements?ids=" + ",".join(achievement_ids)
        results = await cog.call_api(  # type: ignore[attr-defined]
            endpoint, key=doc["key"]
        )
    except APINotFound:
        results = []
        doc = None
    except APIError:
        raise

    def is_completed(encounter):
        if encounter["type"] == "single_achievement":
            _id = encounter["id"]
            for achievement in results:
                if achievement["id"] == _id and achievement["done"]:
                    return "+✔"
            return "-✖"
        if encounter["type"] == "all_achievements":
            for _id in encounter["ids"]:
                if not any(a["id"] == _id and a["done"] for a in results):
                    return "-✖"
            return "+✔"
        if encounter["type"] == "progressed_achievement":
            _id = encounter["id"]
            _progress = encounter["progress"]
            for achievement in results:
                if achievement["id"] == _id and achievement["current"] >= _progress:
                    return "+✔"
            return "-✖"

    embed = discord.Embed(
        title="Kill Proof", color=await cog.get_embed_color(interaction)
    )
    if doc:
        embed.set_author(name=doc["account_name"], icon_url=user.display_avatar.url)
    for area in areas:
        value = ["```diff"]
        encounters = area["encounters"]
        for encounter in encounters:
            value.append(is_completed(encounter) + encounter["name"])
        value.append("```")
        embed.add_field(name=area["name"], value="\n".join(value))

    embed.description = "Achievements were checked to find completed encounters."
    embed.set_footer(
        text=(
            "Green (+) means completed. Red (-) means not. "
            "CM stands for Challenge Mode."
        )
    )

    await interaction.followup.send(embed=embed)
