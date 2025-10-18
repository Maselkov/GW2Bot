import discord
from discord import app_commands

from .. import with_cog


@app_commands.command(
    name="li", description="Shows how many Legendary Insights you have earned"
)
@with_cog()
async def account_li(cog, interaction: discord.Interaction):
    await interaction.response.defer()
    user = interaction.user
    scopes = ["inventories", "characters", "wallet"]
    trophies = cog.gamedata["raid_trophies"]
    ids = []
    for trophy in trophies:
        for items in trophy["items"]:
            ids += items["items"]
    doc = await cog.fetch_key(user, scopes)  # type: ignore[attr-defined]
    search_results = await cog.container.inventory_service.find_items_in_account(
        key=doc["key"], item_ids=ids, doc=doc
    )
    wallet = await cog.container.api.get(  # type: ignore[attr-defined]
        "account/wallet", key=doc["key"]
    )
    embed = discord.Embed(color=0x4C139D)
    total = 0
    crafted_total = 0
    for trophy in trophies:
        trophy_total = 0
        breakdown = []
        if trophy["wallet"]:
            for currency_result in wallet:
                if currency_result["id"] == trophy["wallet"]:
                    trophy_total += currency_result["value"]
                    breakdown.append(f"Wallet - **{currency_result['value']}**")
                    break
        for group in trophy["items"]:
            if "reduced_worth" in group:
                upgraded_sum = 0
                if "upgrades_to" in group:
                    upgrade_dict = next(
                        item
                        for item in trophy["items"]
                        if item.get("name") == group["upgrades_to"]
                    )
                    for item in upgrade_dict["items"]:
                        upgraded_sum += sum(search_results[item].values())
                amount = 0
                for item in group["items"]:
                    amount += sum(search_results[item].values())
                reduced_amount = group["reduced_amount"]
                reduced_amount = max(reduced_amount - upgraded_sum, 0)
                sum_set = (
                    min(amount, reduced_amount) * group["reduced_worth"]
                    + max(amount - reduced_amount, 0) * group["worth"]
                )
                if sum_set:
                    trophy_total += sum_set
                    breakdown.append(f"{amount} {group['name']} - **{sum_set}**")
                    if group["crafted"]:
                        crafted_total += sum_set
                continue
            for item in group["items"]:
                amount = sum(search_results[item].values())
                sum_item = amount * group["worth"]
                if sum_item:
                    trophy_total += sum_item
                    if group["crafted"]:
                        crafted_total += sum_item
                    item_doc = await cog.fetch_item(item)  # type: ignore[attr-defined]
                    line = f"{item_doc['name']} - **{sum_item}**"
                    if group["worth"] != 1:
                        line = f"{amount} " + line
                    breakdown.append(line)
        if trophy_total:
            name = f"{trophy_total} Legendary {trophy['name']} earned"
            embed.add_field(name=name, value="\n".join(breakdown), inline=False)
            total += trophy_total
    embed.title = f"{total} Raid trophies earned".format(total)
    embed.description = "{} on hand, {} used in crafting".format(
        total - crafted_total, crafted_total
    )
    embed.set_author(name=doc["account_name"], icon_url=user.display_avatar.url)
    embed.set_thumbnail(
        url="https://wiki.guildwars2.com/images/5/5e/Legendary_Insight.png"
    )
    embed.set_footer(text=cog.bot.user.name, icon_url=cog.bot.user.display_avatar.url)
    await interaction.followup.send(embed=embed)
