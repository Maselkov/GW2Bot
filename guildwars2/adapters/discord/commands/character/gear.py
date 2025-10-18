import collections
import copy
import re
from typing import cast

import discord
from discord import app_commands
from .. import with_cog

from .....skills import Build
from .....utils.chat import zero_width_space
from .....exceptions import APINotFound
from .autocomplete import character_autocomplete


class CharacterGearDropdown(discord.ui.Select):

    def __init__(self, tabs, tab_type, emojis):
        options = []
        self.is_equipment = tab_type == "equipment"
        for i, tab in enumerate(tabs):
            try:
                emoji = emojis[i]
            except IndexError:
                emoji = None
            options.append(
                discord.SelectOption(
                    label=f"{tab_type.title()} Tab {i+1}",
                    value=str(i),
                    emoji=emoji,
                    description=tab.get("name", ""),
                )
            )

        super().__init__(
            placeholder=f"Select {tab_type} template",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view = cast(CharacterGearView, self.view)
        if self.is_equipment:
            view.active_equipment = int(self.values[0])
        else:
            view.active_build = int(self.values[0])
        embed = view.generate_embed()
        await interaction.response.edit_message(embed=embed)


class CharacterGearView(discord.ui.View):

    def __init__(
        self, equipment_options, build_options, character, emojis, emoji_cache, user
    ):
        super().__init__()
        self.value = None
        self.emojis = emojis
        self.character = character
        self.builds = build_options
        self.equipments = equipment_options
        self.active_build = character.get("active_build_tab", 1) - 1
        self.active_equipment = character.get("active_equipment_tab", 1) - 1
        self.add_item(CharacterGearDropdown(build_options, "build", emojis))
        self.add_item(CharacterGearDropdown(equipment_options, "equipment", emojis))
        self.emojis_cache = emoji_cache
        self.user = user
        self.response = None

    async def on_timeout(self) -> None:
        # Safely remove interactive items to effectively disable the view
        for item in list(self.children):
            try:
                self.remove_item(item)
            except Exception:
                pass
        if self.response:
            resp = cast(discord.Message, self.response)
            await resp.edit(view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.user

    def generate_embed(self):
        build = self.builds[self.active_build]
        equipment = self.equipments[self.active_equipment]
        embed = discord.Embed()
        for field in equipment["fields"]:
            embed.add_field(name=field[0], value=field[1], inline=field[2])
        profession = build["build"].profession
        description = ["Build template:"]
        line = ""
        for i in range(len(self.builds)):
            key = "active" if i == self.active_build else "inactive"
            line += str(self.emojis_cache["build"][key][i])
        if build.get("name"):
            line += f" *{build['name']}*"
        description.append("> " + line)
        description.append("Equipment template:")
        line = ""
        for i in range(len(self.equipments)):
            key = "active" if i == self.active_equipment else "inactive"
            line += str(self.emojis_cache["equipment"][key][i])
        if equipment.get("name"):
            line += f" *{equipment['name']}*"
        description.append("> " + line)
        description = "\n".join(description)
        embed.description = description
        embed.color = profession.color
        footer_text = "A level {} {} ".format(
            self.character["level"], profession.name.lower()
        )
        embed.set_footer(text=footer_text)
        embed.set_author(name=self.character["name"], icon_url=profession.icon)
        embed.add_field(name="Build code", value=build["build"].code, inline=False)
        embed.set_image(url=build["url"])
        return embed


@app_commands.command(name="gear", description="Displays gear, attributes and build")
@app_commands.describe(character="Name of your character")
@app_commands.autocomplete(character=character_autocomplete)
@with_cog()
async def character_gear(cog, interaction: discord.Interaction, character: str):
    """Displays the gear, attributes and build of given character"""
    await interaction.response.defer()
    # Cog injected by decorator; assumed loaded
    if not cog.check_emoji_permission(interaction):
        msg = (
            "The default role in this channel needs to have `use external emojis` "
            "permission in order to use this command."
        )
        return await interaction.followup.send(msg)

    emojis_cache = {
        "build": {"inactive": [], "active": []},
        "equipment": {"inactive": [], "active": []},
    }
    for i in range(1, 11):
        emojis_cache["build"]["inactive"].append(
            cog.get_emoji(interaction, f"build_{i}", return_obj=True)
        )
        emojis_cache["build"]["active"].append(
            cog.get_emoji(interaction, f"active_build_{i}", return_obj=True)
        )
        emojis_cache["equipment"]["inactive"].append(
            cog.get_emoji(interaction, f"build_{i}", return_obj=True)
        )
        emojis_cache["equipment"]["active"].append(
            cog.get_emoji(interaction, f"active_build_{i}", return_obj=True)
        )

    async def get_equipment_fields(tab, eq, results):
        fields = []
        runes = collections.defaultdict(int)
        bonuses = collections.defaultdict(int)
        armor_lines = []
        trinket_lines = []
        weapon_sets = {"A": [], "B": []}
        armors = ["Helm", "Shoulders", "Coat", "Gloves", "Leggings", "Boots"]
        trinkets = [
            "Ring1",
            "Ring2",
            "Amulet",
            "Accessory1",
            "Accessory2",
            "Backpack",
        ]
        weapons = ["WeaponA1", "WeaponA2", "WeaponB1", "WeaponB2"]
        pieces = armors + trinkets + weapons
        for piece in pieces:
            piece_name = piece[:-1] if piece[-1:].isdigit() else piece
            line = ""
            stat_name = ""
            upgrades_to_display = []
            for item in eq:
                if item["slot"] == piece:
                    svc = cog.container.characters_service
                    item_doc = await svc.fetch_item(item["id"]) or {}
                    line = cog.get_emoji(
                        interaction, f"{item_doc['rarity']}_{piece_name}"
                    )
                    for upgrade_type in ("infusions", "upgrades"):
                        if upgrade_type in item:
                            for upgrade in item[upgrade_type]:
                                cs = cog.container.characters_service
                                upgrade_doc = await cs.fetch_item(upgrade)
                                if not upgrade_doc:
                                    upgrades_to_display.append("Unknown upgrade")
                                    continue
                                details = upgrade_doc["details"]
                                if details["type"] == "Rune":
                                    runes[upgrade_doc["name"]] += 1
                                if details["type"] == "Sigil":
                                    upgrades_to_display.append(upgrade_doc["name"])
                                if (
                                    "infix_upgrade" in details
                                    and "attributes" in details["infix_upgrade"]
                                ):
                                    for attribute in details["infix_upgrade"][
                                        "attributes"
                                    ]:
                                        name = attribute["attribute"]
                                        bonuses[name] += attribute["modifier"]
                    if "stats" in item:
                        stat_name = await svc.fetch_stat_name(item["stats"]["id"])
                    else:
                        try:
                            stat_id = item_doc["details"]["infix_upgrade"]["id"]
                            stat_name = await svc.fetch_stat_name(stat_id)
                        except KeyError:
                            pass
                    line += stat_name
                    if piece.startswith("Weapon"):
                        line += " " + svc.readable_attribute(
                            item_doc["details"]["type"]
                        )
                    if upgrades_to_display:
                        line += "\n*{}*".format("\n".join(upgrades_to_display))
            if not line and not piece.startswith("Weapon"):
                line = cog.get_emoji(interaction, f"basic_{piece_name}") + "NONE"
            if piece in armors:
                armor_lines.append(line)
            elif piece in weapons:
                if line:
                    weapon_sets[piece[-2]].append(line)
            elif piece in trinkets:
                trinket_lines.append(line)
        lines = []
        lines.append("\n".join(armor_lines))
        if runes:
            for rune, count in runes.items():
                lines.append(f"*{rune}* ({count}/6)")
        fields.append(("> **ARMOR**", "\n".join(lines), True))
        if any(weapon_sets["A"]):
            fields.append(("> **WEAPON SET #1**", "\n".join(weapon_sets["A"]), True))
        if any(weapon_sets["B"]):
            fields.append(("> **WEAPON SET #2**", "\n".join(weapon_sets["B"]), True))
        fields.append(("> **TRINKETS**", "\n".join(trinket_lines), False))
        upgrade_lines = []
        for bonus, count in bonuses.items():
            bonus_r = cog.container.characters_service.readable_attribute(bonus)
            emoji = cog.get_emoji(interaction, f"attribute_{bonus_r}")
            upgrade_lines.append(f"{emoji}**{bonus_r}**: {count}")
        if not upgrade_lines:
            upgrade_lines = ["None found"]
        fields.append(("> **BONUSES FROM UPGRADES**", "\n".join(upgrade_lines), False))
        attributes = await cog.container.characters_service.calculate_attributes(
            results, eq
        )
        column_1 = []
        column_2 = [zero_width_space, zero_width_space]
        for index, (name, value) in enumerate(attributes.items()):
            line = cog.get_emoji(interaction, f"attribute_{name}")
            line += f"**{name}**: {value}"
            if index < 9:
                column_1.append(line)
            else:
                column_2.append(line)
        fields.append(("> **ATTRIBUTES**", "\n".join(column_1), True))
        fields.append((zero_width_space, "\n".join(column_2), True))
        return fields

    cog_doc = await cog.bot.database.get_cog_config(cog)
    if not cog_doc:
        return await interaction.followup.send("Eror reading configuration")
    image_channel = cog.bot.get_channel(cog_doc.get("image_channel"))
    if not image_channel:
        return await interaction.followup.send(
            "The owner must set the image channel using $imagechannel command."
        )

    # Get key with required scopes for gear/builds
    try:
        key_doc = await cog.container.keys_service.get_key_for_user(
            interaction.user, required_scopes=["characters", "builds"], cog=cog
        )
    except Exception:
        return await interaction.followup.send(
            "No API key with 'characters,builds' found. Add a key with /key add."
        )
    try:
        results = await cog.container.characters_service.get_character_by_key(
            name=character, key=key_doc["key"]
        )
    except APINotFound:
        # fallback to public if available
        pub = await cog.container.repo.get_public_character(character.title())
        if not pub:
            return await interaction.followup.send("Invalid character name")
        try:
            owner = await cog.bot.fetch_user(pub["owner"])  # type: ignore[index]
            owner_key = await cog.container.keys_service.get_key_for_user(
                owner, required_scopes=["characters", "builds"], cog=cog
            )
            results = await cog.container.characters_service.get_character_by_key(
                name=character, key=owner_key["key"]
            )
        except Exception:
            return await interaction.followup.send("Invalid character name")

    build_tabs = results.get("build_tabs", [])
    equipment_tabs = results.get("equipment_tabs", [])

    builds = []
    for tab in build_tabs:
        build = await Build.from_build_tab(cog, tab)
        if not build:
            continue
        file = await build.render(filename=f"build_{tab['tab']}.png")
        is_active = tab.get("is_active")
        name = tab.get("build", {}).get("name")
        builds.append(
            {
                "tab": tab["tab"],
                "file": file,
                "name": name,
                "is_active": is_active,
                "build": build,
                "url": "",
            }
        )

    equipments = []
    for tab in equipment_tabs:
        eq = []
        for item_1 in tab.get("equipment", []):
            if "stats" in item_1:
                eq.append(item_1)
                continue
            for item_2 in results.get("equipment", []):
                if item_1["id"] != item_2["id"]:
                    continue
                if tab["tab"] in item_2.get("tabs", []):
                    item_copy = copy.copy(item_2)
                    item_copy["slot"] = item_1["slot"]
                    eq.append(item_copy)
                    break
        equipments.append(
            {
                "fields": await get_equipment_fields(tab, eq, results),
                "name": tab.get("name"),
            }
        )

    # Send build images to the configured image channel and capture URLs
    if builds:
        images_msg = await image_channel.send(
            files=[b["file"] for b in builds if b["file"]]
        )
        urls = [attachment.url for attachment in images_msg.attachments]
        for url in urls:
            m = re.search(r"build_\d*\.png", url)
            if not m:
                continue
            file_name = m.group(0)
            tab_id = int("".join(c for c in file_name if c.isdigit()))
            for t in builds:
                if t["tab"] == tab_id:
                    t["url"] = url
                    break

    numbers = emojis_cache["build"]["active"][: len(builds)] if builds else []
    view = CharacterGearView(
        equipments, builds, results, numbers, emojis_cache, interaction.user
    )
    embed = view.generate_embed()
    out = await interaction.followup.send(embed=embed, view=view)
    view.response = out
