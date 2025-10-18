import discord
from discord import app_commands

from .. import with_cog


@app_commands.command(
    name="nodes",
    description="Displays the home instance nodes you have not yet unlocked.",
)
@with_cog()
async def account_nodes(cog, interaction: discord.Interaction):
    await interaction.response.defer()
    user = interaction.user
    endpoint = "account/home/nodes"
    doc = await cog.fetch_key(user, ["progression"])  # type: ignore[attr-defined]
    results = await cog.call_api(endpoint, key=doc["key"])  # type: ignore[attr-defined]
    owned_nodes = results
    lines = []
    for nodes in cog.gamedata["nodes"]:
        if nodes["id"] not in owned_nodes:
            lines.append(nodes["guide"])
    if not lines:
        return await interaction.followup.send(
            "You've collected all home instance nodes! Congratulations!"
        )
    embed = discord.Embed(color=await cog.get_embed_color(interaction))
    embed.title = "Nodes you haven't collected yet:"
    embed.description = "\n".join(lines)
    embed.set_author(name=doc["account_name"], icon_url=user.display_avatar.url)
    embed.set_footer(text=cog.bot.user.name, icon_url=cog.bot.user.display_avatar.url)
    await interaction.followup.send(embed=embed)
