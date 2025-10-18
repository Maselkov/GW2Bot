import discord
from discord import app_commands

from .. import with_cog


@app_commands.command(
    name="cats", description="Displays the cats you haven't unlocked yet"
)
@with_cog()
async def account_cats(cog, interaction: discord.Interaction):
    await interaction.response.defer()
    user = interaction.user
    endpoint = "account/home/cats"
    doc = await cog.fetch_key(user, ["progression"])  # type: ignore[attr-defined]
    results = await cog.call_api(endpoint, key=doc["key"])  # type: ignore[attr-defined]
    owned_cats = [cat["id"] for cat in results]
    lines = []
    for cat in cog.gamedata["cats"]:
        if cat["id"] not in owned_cats:
            lines.append(cat["guide"])
    if not lines:
        return await interaction.followup.send(
            "You have collected all the cats! Congratulations! :cat2:"
        )
    embed = discord.Embed(color=await cog.get_embed_color(interaction))
    embed = embed
    embed.title = "Cats you haven't collected yet"
    embed.description = "\n".join(lines)
    embed.set_author(name=doc["account_name"], icon_url=user.display_avatar.url)
    embed.set_footer(text=cog.bot.user.name, icon_url=cog.bot.user.display_avatar.url)
    await interaction.followup.send(embed=embed)
