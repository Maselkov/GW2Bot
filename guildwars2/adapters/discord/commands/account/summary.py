import re

import discord
from discord import app_commands
from .. import with_cog
from .....types import GuildWars2Cog


@app_commands.command(
    name="account", description="General information about your account"
)
@with_cog()
async def account_summary(cog: GuildWars2Cog, interaction: discord.Interaction):
    """Implements the /account summary command; called by the Cog method."""
    await interaction.response.defer()
    user = interaction.user
    container = cog.container

    # Centralized key retrieval and scope validation
    key_doc = await container.keys_service.get_key_for_user(
        user, required_scopes=["account"], cog=cog
    )

    data = await container.account_service.get_account(key=key_doc["key"])

    embed = discord.Embed(colour=await cog.get_embed_color(interaction))

    # Created date
    created_raw = data.get("created")
    if created_raw:
        created = created_raw.split("T", 1)[0]
        embed.add_field(name="Created account on", value=created)

    # WvW server
    wid = data.get("world")
    if wid:
        world = await cog.get_world_name(wid)
        if world:
            embed.add_field(name="WvW Server", value=world)

    # Commander tag
    has_commander = "Yes" if data.get("commander") else "No"
    embed.add_field(name="Commander tag", value=has_commander, inline=False)

    # Fractal level and WvW rank
    if "fractal_level" in data:
        embed.add_field(name="Fractal level", value=data["fractal_level"])
    if "wvw_rank" in data:
        embed.add_field(name="WvW rank", value=data["wvw_rank"])

    # PvP rank if permission present
    if "pvp" in key_doc.get("permissions", []):
        pvp = await container.account_service.get_pvp_stats(key=key_doc["key"])
        pvprank = pvp.get("pvp_rank", 0) + pvp.get("pvp_rank_rollovers", 0)
        embed.add_field(name="PVP rank", value=pvprank)

    # Optional enrichments via permissions
    try:
        if "progression" in key_doc.get("permissions", []):
            ach_res, acc_res = await container.api.get_many(
                ["account/achievements", "account"], key=key_doc["key"]
            )
            possible_ap = await container.achievements_service.total_possible_ap()
            user_ap = await container.achievements_service.calculate_user_ap(
                ach_res, acc_res
            )
            embed.add_field(
                name="Achievement Points",
                value=f"{user_ap} earned out of {possible_ap} possible",
                inline=False,
            )

        if "characters" in key_doc.get("permissions", []):
            chars = await container.characters_service.get_all_characters(
                key=key_doc["key"]
            )
            total_played = container.characters_service.total_play_time(chars)
            embed.add_field(
                name="Total time played",
                value=cog.format_age(total_played),
                inline=False,
            )
    except Exception:
        pass

    # Expansion access
    access = data.get("access")
    if access:
        access_list = list(access)
        if len(access_list) > 1:
            for d in ("PlayForFree", "GuildWars2"):
                if d in access_list:
                    access_list.remove(d)
            if "PathOfFire" in access_list and "HeartOfThorns" not in access_list:
                access_list.append("HeartOfThorns")

        def format_name(name):
            return " ".join(re.findall(r"[A-Z\d][^A-Z\d]*", name))

        access_str = "\n".join(format_name(e) for e in access_list)
        if access_str:
            embed.add_field(name="Expansion access", value=access_str)

    embed.set_author(name=key_doc["account_name"], icon_url=user.display_avatar.url)
    embed.set_footer(text=cog.bot.user.name, icon_url=cog.bot.user.display_avatar.url)
    await interaction.followup.send(embed=embed)


# No wrapper needed; loader auto-registers via the decorator above
