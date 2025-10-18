import datetime

import discord
from discord import app_commands

from .. import with_cog


@app_commands.command(
    name="bosses", description="Shows your raid progression for the week"
)
@with_cog()
async def account_bosses(cog, interaction: discord.Interaction):
    await interaction.response.defer()
    user = interaction.user
    scopes = ["progression"]
    endpoints = ["account/raids", "account"]
    doc = await cog.fetch_key(user, scopes)  # type: ignore[attr-defined]
    schema = datetime.datetime(2019, 2, 21)
    results, account = await cog.call_multiple(  # type: ignore[attr-defined]
        endpoints, key=doc["key"], schema_version=schema
    )
    last_modified = datetime.datetime.strptime(
        account["last_modified"], "%Y-%m-%dT%H:%M:%Sz"
    )
    raids = await cog.get_raids()  # type: ignore[attr-defined]

    # Build the weekly bosses embed (inlined from previous mixin)
    from collections import defaultdict

    boss_to_id = defaultdict(list)
    for boss_id, boss in cog.gamedata["bosses"].items():
        if "api_name" in boss:
            boss_to_id[boss["api_name"]].append(int(boss_id))

    def is_killed(boss):
        return ":white_check_mark:" if boss["id"] in results else ":x:"

    def readable_id(_id: str) -> str:
        parts = _id.split("_")
        dont_capitalize = ("of", "the", "in")
        title = " ".join(
            [p.capitalize() if p not in dont_capitalize else p for p in parts]
        )
        return title[0].upper() + title[1:]

    monday = last_modified - datetime.timedelta(days=last_modified.weekday())
    if not last_modified.weekday():
        if last_modified < last_modified.replace(
            hour=7, minute=30, second=0, microsecond=0
        ):
            monday = last_modified - datetime.timedelta(weeks=1)
    reset_time = datetime.datetime(
        monday.year, monday.month, monday.day, hour=7, minute=30
    )
    next_reset_time = reset_time + datetime.timedelta(weeks=1)

    async def get_dps_reports(boss_id: str):
        ids = boss_to_id[boss_id]
        cursor = (
            cog.db.encounters.find(  # type: ignore[attr-defined]
                {
                    "boss_id": {"$in": ids},
                    "players": doc["account_name"],
                    "date": {"$gte": reset_time, "$lt": next_reset_time},
                    "success": boss["id"] in results,  # type: ignore[name-defined]
                }
            )
            .sort("date", -1)
            .limit(5)
        )
        return await cursor.to_list(None)

    not_completed = []
    embed = discord.Embed(title="Bosses", color=await cog.get_embed_color(interaction))
    wings = [wing for raid in raids for wing in raid["wings"]]
    cotm = cog.get_emoji(interaction, "call_of_the_mists")
    emboldened = cog.get_emoji(interaction, "emboldened")
    start_date = datetime.date(year=2022, month=6, day=20)
    current = datetime.datetime.utcnow().date()
    monday_1 = start_date - datetime.timedelta(days=start_date.weekday())
    monday_2 = current - datetime.timedelta(days=current.weekday())
    weeks = (monday_2 - monday_1).days // 7
    cotm_index = weeks % len(wings)
    emboldened_index = (weeks - 1) % len(wings)
    for index, wing in enumerate(wings):
        wing_done = True
        value = []
        for boss in wing["events"]:
            if boss["id"] not in results:
                wing_done = False
                not_completed.append(boss)
            reports = await get_dps_reports(boss["id"])
            if reports:
                boss_name = f"[{readable_id(boss['id'])}]({reports[0]['permalink']})"
                if len(reports) > 1:
                    links = []
                    for i, report in enumerate(reports[1:], 2):
                        links.append(f"[{i}]({report['permalink']})")
                    boss_name += f" ({', '.join(links)})"
            else:
                boss_name = readable_id(boss["id"])
            value.append("> " + is_killed(boss) + boss_name)
        name = readable_id(wing["id"])
        if index == cotm_index:
            name = f"{cotm}{name}"
        elif index == emboldened_index:
            name = f"{emboldened}{name}"
        if wing_done:
            name += " :white_check_mark:"
        else:
            name += " :x:"
        embed.add_field(name=f"**{name}**", value="\n".join(value))
    if len(not_completed) == 0:
        description = "Everything completed this week :star:"
    else:
        bosses_list = list(filter(lambda b: b["type"] == "Boss", not_completed))
        events_list = list(filter(lambda b: b["type"] == "Checkpoint", not_completed))
        bosses_str = None
        events_str = None
        if bosses_list:
            suffix = "es" if len(bosses_list) > 1 else ""
            bosses_str = f"{len(bosses_list)} boss{suffix}"
        if events_list:
            suffix = "s" if len(events_list) > 1 else ""
            events_str = f"{len(events_list)} event{suffix}"
        parts = [p for p in [bosses_str, events_str] if p]
        description = ", ".join(parts) + " not completed this week"
    if datetime.datetime.utcnow() > next_reset_time:
        description = description.replace("this", "that")
        description += (
            "\n❗Warning❗\n Data outdated for this week. Log into GW2 in order to"
            " update."
        )
    embed.description = description
    embed.set_footer(
        text=(
            "Logs uploaded via evtc will appear here with links - "
            "they don't have to be uploaded by you"
        ),
        icon_url=cog.bot.user.display_avatar.url,
    )
    embed.set_author(name=doc["account_name"], icon_url=user.display_avatar.url)
    await interaction.followup.send(embed=embed)
