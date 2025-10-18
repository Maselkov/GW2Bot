import asyncio
from collections import OrderedDict
from typing import Any

import discord
from discord import app_commands

from .. import with_cog
from .....utils.db import prepare_search
from .....types import GuildWars2Cog


@with_cog()
async def item_autocomplete(
    cog: GuildWars2Cog, interaction: discord.Interaction, current: str
):
    if not current:
        return []

    def consolidate_duplicates(items):
        unique_items = OrderedDict()
        for item in items:
            item_tuple = item["name"], item["rarity"], item["type"]
            if item_tuple not in unique_items:
                unique_items[item_tuple] = []
            unique_items[item_tuple].append(item["_id"])
        unique_list = []
        for k, v in unique_items.items():
            ids = " ".join(str(i) for i in v)
            if len(ids) > 100:
                continue
            unique_list.append({"name": k[0], "rarity": k[1], "ids": ids, "type": k[2]})
        return unique_list

    query = prepare_search(current)
    query = {"name": query}
    items = await cog.db.items.find(query).to_list(25)
    items = sorted(consolidate_duplicates(items), key=lambda c: c["name"])
    return [
        app_commands.Choice(name=f"{it['name']} - {it['rarity']}", value=it["ids"])
        for it in items
    ]


@app_commands.command(name="search", description="Find items on your account")
@app_commands.describe(
    item="Specify the name of an item to search for. Select an item from the list."
)
@app_commands.autocomplete(item=item_autocomplete)
@with_cog()
async def account_search(
    cog: GuildWars2Cog, interaction: discord.Interaction, item: str
):
    await interaction.response.defer()
    try:
        ids = [int(it) for it in item.split(" ")]
    except ValueError:
        try:
            choices = await item_autocomplete(interaction, item)
            ids = [int(it.value.split(" ")[0]) for it in choices]
        except (ValueError, IndexError):
            return await interaction.followup.send(
                "Could not find any items with that name."
            )
    item_doc = await cog.fetch_item(ids[0])  # type: ignore[attr-defined]

    async def generate_results_embed(results: dict[str, Any]):
        seq = [k for k, v in results.items() if v]
        if not seq:
            return None
        longest = len(max(seq, key=len))
        if longest < 8:
            longest = 8
        if "is_upgrade" in item_doc and item_doc["is_upgrade"]:
            output = [
                "LOCATION{}INV / GEAR".format(" " * (longest - 5)),
                "--------{}|-----".format("-" * (longest - 6)),
            ]
            align = 110
        else:
            output = [
                "LOCATION{}COUNT".format(" " * (longest - 5)),
                "--------{}|-----".format("-" * (longest - 6)),
            ]
            align = 80
        total = 0
        storage_counts = OrderedDict(
            sorted(results.items(), key=lambda kv: kv[1], reverse=True)
        )
        # Fetch character names via service to avoid relying on Cog methods
        try:
            doc_local = doc  # capture from outer scope
            chars = await cog.container.characters_service.get_all_characters(
                key=doc_local["key"]  # type: ignore[index]
            )
            char_names = [c.get("name", "") for c in chars]
        except Exception:
            char_names = []
        for k, v in storage_counts.items():
            if v:
                if "is_upgrade" in item_doc and item_doc["is_upgrade"]:
                    total += v[0]
                    total += v[1]
                    if k in char_names:
                        slotted_upg = v[1]
                        inf = "" if slotted_upg == 0 else f"/ {slotted_upg} "
                        output.append(
                            f"{k.upper()} {' ' * (longest - len(k))} | {v[0]} {inf}"
                        )
                    else:
                        output.append(
                            f"{k.upper()} {' ' * (longest - len(k))} | {v[0]}"
                        )
                else:
                    total += v[0]
                    total += v[1]
                    output.append(
                        f"{k.upper()} {' ' * (longest - len(k))} | {v[0] + v[1]}"
                    )
        output.append("--------{}------".format("-" * (longest - 5)))
        output.append("TOTAL:{}{}".format(" " * (longest - 2), total))
        color = int(cog.gamedata["items"]["rarity_colors"][item_doc["rarity"]], 16)
        icon_url = item_doc["icon"]
        data = discord.Embed(
            description="Search results" + "\u00a0" * align + "\u200b", color=color
        )
        value = "\n".join(output)

        if len(value) > 1014:
            value = ""
            values = []
            for line in output:
                if len(value) + len(line) > 1013:
                    values.append(value)
                    value = ""
                value += line + "\n"
            if value:
                values.append(value)
            data.add_field(
                name=item_doc["name"], value=f"```ml\n{values[0]}```", inline=False
            )
            for v in values[1:]:
                data.add_field(name="\u200b", value=f"```ml\n{v}```", inline=False)
        else:
            data.add_field(name=item_doc["name"], value=f"```ml\n{value}\n```")
        data.set_author(
            name=doc["account_name"],  # type: ignore[name-defined]
            icon_url=interaction.user.display_avatar.url,
        )
        if "is_upgrade" in item_doc and item_doc["is_upgrade"]:
            data.set_footer(
                text="Amount in inventory / Amount in gear",
                icon_url=cog.bot.user.display_avatar.url,
            )
        else:
            data.set_footer(
                text=cog.bot.user.name, icon_url=cog.bot.user.display_avatar.url
            )
        data.set_thumbnail(url=icon_url)
        return data

    user = interaction.user
    doc = await cog.fetch_key(  # type: ignore[attr-defined]
        user, ["inventories", "characters"]
    )
    endpoints = [
        "account/bank",
        "account/inventory",
        "account/materials",
        "characters?page=0&page_size=200",
    ]
    task = asyncio.create_task(
        cog.container.api.get_many(
            endpoints, key=doc["key"], schema_string="2021-07-15T13:00:00.000Z"
        )
    )
    storage = None
    if not task.done():
        storage = await task
    if exc := task.exception():
        raise exc
    search_results = await cog.container.inventory_service.find_items_in_account(
        key=doc["key"],
        item_ids=ids,
        doc=doc,
        flatten=True,
        search=True,
        results=storage,
    )
    embed = await generate_results_embed(search_results)
    if not embed:
        return await interaction.followup.send(
            content=f"`{item_doc['name']}`: Not found on your account."
        )
    return await interaction.followup.send(embed=embed)
