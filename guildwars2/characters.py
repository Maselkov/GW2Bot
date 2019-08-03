import asyncio
import collections
import datetime
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError, APINotFound
from .utils.chat import embed_list_lines, zero_width_space


class Character:
    def __init__(self, cog, data):
        self.cog = cog
        self.data = data
        self.name = data["name"]
        self.race = data["race"]
        self.gender = data["gender"].lower()
        self.profession = data["profession"].lower()
        self.level = data["level"]
        self.specializations = data.get("specializations")
        self.color = discord.Color(
            int(self.cog.gamedata["professions"][self.profession]["color"],
                16))
        self.created = datetime.datetime.strptime(data["created"],
                                                  "%Y-%m-%dT%H:%M:%Sz")
        self.age = data["age"]
        self.spec_cache = {}

    async def get_spec_info(self, mode="pve"):
        async def get_elite_spec():
            if not self.specializations:
                return self.profession.title()
            spec = self.specializations[mode][2]
            if spec:
                spec = await self.cog.db.specializations.find_one({
                    "_id":
                    spec["id"]
                })
                if spec is None or not spec["elite"]:
                    return self.profession.title()
                return spec["name"]
            return self.profession.title()

        def get_icon_url(prof_name):
            base_url = ("https://api.gw2bot.info/"
                        "resources/professions/{}_icon.png")
            return base_url.format(prof_name.replace(" ", "_").lower())

        name = await get_elite_spec()
        icon = get_icon_url(name)
        info = {"name": name, "icon": icon}
        self.spec_cache[mode] = info
        return info


class CharactersMixin:
    @staticmethod
    def format_age(age, *, short=False):
        hours, seconds = divmod(age, 3600)
        minutes = round(seconds / 60)
        h_str = "h" if short else " hours"
        m_str = "m" if short else " minutes"
        if hours:
            return "{}{} {}{}".format(hours, h_str, minutes, m_str)
        return "{}{}".format(minutes, m_str)

    @commands.group(case_insensitive=True)
    async def character(self, ctx):
        """Character related commands"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @character.command(name="fashion")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_fashion(self, ctx, *, character: str):
        """Displays the fashion wars of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        character = character.title()
        await ctx.trigger_typing()
        try:
            results = await self.get_character(ctx, character)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        eq = results["equipment"]
        gear = {}
        pieces = [
            "Helm", "Shoulders", "Coat", "Gloves", "Leggings", "Boots",
            "Backpack", "WeaponA1", "WeaponA2", "WeaponB1", "WeaponB2"
        ]
        gear = {piece: {} for piece in pieces}
        profession = await self.get_profession(results)
        level = results["level"]
        for item in eq:
            slot = item["slot"]
            if slot not in pieces:
                continue
            dye_ids = item.get("dyes", [])
            dyes = []
            for dye in dye_ids:
                if dye:
                    doc = await self.db.colors.find_one({"_id": dye})
                    if doc:
                        dyes.append(doc["name"])
                        continue
                dyes.append(None)
            gear[slot]["dyes"] = dyes
            skin = item.get("skin")
            if skin:
                doc = await self.db.skins.find_one({"_id": skin})
                if doc:
                    gear[slot]["name"] = doc["name"]
                    continue
            doc = await self.db.items.find_one({"_id": item["id"]})
            gear[slot]["name"] = doc["name"]

        embed = discord.Embed(description="Fashion", colour=profession.color)
        for piece in pieces:
            info = gear[piece]
            if not info:
                continue
            value = []
            for i, dye in enumerate(info["dyes"], start=1):
                if dye:
                    value.append(f"Channel {i}: {dye}")
            value = "\n".join(value)
            if not value:
                value = zero_width_space
            embed.add_field(name=info["name"], value=value, inline=False)
        embed.set_author(name=character)
        embed.set_footer(
            text="A level {} {} ".format(level, profession.name.lower()),
            icon_url=profession.icon)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden as e:
            await ctx.send("Need permission to embed links")

    @character.command(name="info")
    @commands.cooldown(1, 5, BucketType.user)
    async def character_info(self, ctx, *, character: str):
        """Info about the given character
        You must be the owner of the character.

        Required permissions: characters
        """

        await ctx.trigger_typing()
        character = character.title()
        endpoint = "characters/" + character.replace(" ", "%20")
        scopes = ["characters", "builds"]
        try:
            results = await self.call_api(endpoint, ctx.author, scopes)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        age = self.format_age(results["age"])
        created = results["created"].split("T", 1)[0]
        deaths = results["deaths"]
        deathsperhour = round(deaths / (results["age"] / 3600), 1)
        if "title" in results:
            title = await self.get_title(results["title"])
        else:
            title = None
        profession = await self.get_profession(results)
        gender = results["gender"]
        race = results["race"].lower()
        guild = results["guild"]
        data = discord.Embed(description=title, colour=profession.color)
        data.set_thumbnail(url=profession.icon)
        data.add_field(name="Created at", value=created)
        data.add_field(name="Played for", value=age)
        if guild is not None:
            endpoint = "guild/{0}".format(results["guild"])
            try:
                guild = await self.call_api(endpoint)
            except APIError as e:
                return await self.error_handler(ctx, e)
            gname = guild["name"]
            gtag = guild["tag"]
            data.add_field(name="Guild", value="[{}] {}".format(gtag, gname))
        data.add_field(name="Deaths", value=deaths)
        data.add_field(
            name="Deaths per hour", value=str(deathsperhour), inline=False)
        craft_list = self.get_crafting(results)
        if craft_list:
            data.add_field(name="Crafting", value="\n".join(craft_list))
        data.set_author(name=character)
        data.set_footer(text="A {} {} {}".format(gender.lower(), race,
                                                 profession.name.lower()))
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @character.command(
        name="list", usage="<sort (name|profession|created|age)>")
    @commands.cooldown(1, 5, BucketType.user)
    async def character_list(self, ctx, sort="name"):
        """Lists all your characters, with extra info (age|created|profession)

        You can specify a sort parameter which can be
        name, profession, created (date of creation), or age (time played).
        Defaults to name.
        Required permissions: characters
        """

        sort = sort.lower()
        if sort not in ("profession", "name", "created", "age"):
            return await ctx.send_help(ctx.command)

        def get_sort_key():
            if sort == "profession":
                return lambda k: (k.profession, k.name)
            if sort == "age":
                return lambda k: (-k.age, k.name)
            if sort == "created":
                return lambda k: (-(
                    datetime.datetime.utcnow() - k.created).total_seconds(),
                    k.name)
            return lambda k: k.name

        def extra_info(char):
            if sort == "age":
                return ": " + self.format_age(char.age, short=True)
            if sort == "created":
                return ": " + char.created.strftime("%Y-%m-%d")
            is_80 = char.level == 80
            return "" + (" (Level {})".format(char.level) if not is_80 else "")

        user = ctx.author
        scopes = ["characters", "builds"]
        await ctx.trigger_typing()
        try:
            doc = await self.fetch_key(user, scopes)
            characters = await self.get_all_characters(user)
        except APIError as e:
            return await self.error_handler(ctx, e)
        embed = discord.Embed(
            title="Your characters", colour=await self.get_embed_color(ctx))
        embed.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        output = []
        for character in sorted(characters, key=get_sort_key()):
            spec = await character.get_spec_info()
            output.append("{}**{}**{}".format(
                self.get_emoji(
                    ctx, spec["name"], fallback=True,
                    fallback_fmt="**({})** "), character.name,
                extra_info(character)))
        sort = {
            "created": "date of creation",
            "age": "time played"
        }.get(sort, sort)
        embed = embed_list_lines(embed, output, "List")
        embed.description = "Sorted by " + sort
        embed.set_footer(text="You can use age|created|profession to "
                         "display more information! E.g. {}character list age".
                         format(ctx.prefix))
        await ctx.send("{.mention}".format(user), embed=embed)

    async def display_gear(self, ctx, character, mode="pve"):
        character = character.title()
        await ctx.trigger_typing()
        try:
            results = await self.get_character(ctx, character)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        task = asyncio.create_task(self.render_traitlines(results, mode=mode))
        eq = results["equipment"]
        profession = await self.get_profession(results, mode=mode)
        description = mode.upper() + " Build" if mode != "pve" else "Build"
        embed = discord.Embed(description=description, colour=profession.color)
        runes = collections.defaultdict(int)
        bonuses = collections.defaultdict(int)
        can_use_emojis = ctx.channel.permissions_for(ctx.me).external_emojis
        if mode in ("pve", "wvw"):
            armor_lines = []
            trinket_lines = []
            weapon_sets = {"A": [], "B": []}
            armors = [
                "Helm", "Shoulders", "Coat", "Gloves", "Leggings", "Boots"
            ]
            trinkets = [
                "Ring1", "Ring2", "Amulet", "Accessory1", "Accessory2",
                "Backpack"
            ]
            weapons = ["WeaponA1", "WeaponA2", "WeaponB1", "WeaponB2"]
            pieces = armors + trinkets + weapons
            for piece in pieces:
                piece_name = piece
                if piece[-1].isdigit():
                    piece_name = piece[:-1]
                line = ""
                stat_name = ""
                upgrades_to_display = []
                for item in eq:
                    if item["slot"] == piece:
                        item_doc = await self.fetch_item(item["id"])
                        if can_use_emojis:
                            line = self.get_emoji(
                                ctx, f"{item_doc['rarity']}_{piece_name}")
                        else:
                            if piece.startswith("Weapon"):
                                if piece.endswith("1"):
                                    piece_name = "Main hand"
                                else:
                                    piece_name = "Off hand"
                            line = f"**{piece_name}**: {item_doc['rarity']} "
                        for upgrade_type in "infusions", "upgrades":
                            if upgrade_type in item:
                                for upgrade in item[upgrade_type]:
                                    upgrade_doc = await self.db.items.find_one(
                                        {
                                            "_id": upgrade
                                        })
                                    details = upgrade_doc["details"]
                                    if details["type"] == "Rune":
                                        runes[upgrade_doc["name"]] += 1
                                    if details["type"] == "Sigil":
                                        upgrades_to_display.append(
                                            upgrade_doc["name"])
                                    if "infix_upgrade" in details:
                                        if "attributes" in details[
                                                "infix_upgrade"]:
                                            for attribute in details[
                                                    "infix_upgrade"][
                                                        "attributes"]:
                                                bonuses[attribute[
                                                    "attribute"]] += attribute[
                                                        "modifier"]
                        if "stats" in item:
                            stat_name = await self.fetch_statname(
                                item["stats"]["id"])
                        else:
                            try:
                                stat_id = item_doc["details"]["infix_upgrade"][
                                    "id"]
                                stat_name = await self.fetch_statname(stat_id)
                            except KeyError:
                                pass
                        line += stat_name
                        if piece.startswith("Weapon"):
                            line += " " + item_doc["details"]["type"]
                        if upgrades_to_display:
                            line += f"\n*{' & '.join(upgrades_to_display)}*"
                if not line and not piece.startswith("Weapon"):
                    if can_use_emojis:
                        line = self.get_emoji(ctx,
                                              f"basic_{piece_name}") + "NONE"
                    else:
                        line = f"**{piece_name}**: NONE"
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
            embed.add_field(name="> **ARMOR**", value="\n".join(lines))
            embed.add_field(
                name="> **TRINKETS**", value="\n".join(trinket_lines))
            if any(weapon_sets["A"]):
                embed.add_field(
                    name="> **WEAPON SET #1**",
                    value="\n".join(weapon_sets["A"]))
            if any(weapon_sets["B"]):
                embed.add_field(
                    name="> **WEAPON SET #2**",
                    value="\n".join(weapon_sets["B"]))
            upgrade_lines = []
            for bonus, count in bonuses.items():
                emoji = self.get_emoji(ctx, f"attribute_{bonus}")
                bonus = self.readable_attribute(bonus)
                upgrade_lines.append(f"{emoji}**{bonus}**: {count}")
            if not upgrade_lines:
                upgrade_lines = ["None found"]
            embed.add_field(
                name="> **BONUSES FROM UPGRADES**",
                value="\n".join(upgrade_lines),
                inline=False)
            attributes = await self.calculate_character_attributes(results)
            column_1 = []
            column_2 = [zero_width_space,
                        zero_width_space]  # cause power is in a different row
            for index, (name, value) in enumerate(attributes.items()):
                line = self.get_emoji(ctx, f"attribute_{name}")
                line += f"**{name}**: {value}"
                if index < 9:
                    column_1.append(line)
                else:
                    column_2.append(line)
            embed.add_field(name="> **ATTRIBUTES**", value="\n".join(column_1))
            embed.add_field(name=zero_width_space, value="\n".join(column_2))
        else:
            if "equipment_pvp" not in results:
                return await ctx.send("API key missing pvp permission")
            amulet = results["equipment_pvp"]["amulet"]
            amulet_doc = await self.db.pvp_amulets.find_one({"_id": amulet})
            if amulet_doc:
                lines = [f"**{amulet_doc['name']}"]
                attributes = amulet_doc["attributes"]
                for name, value in attributes.items():
                    name = self.readable_attribute(name)
                    line = self.get_emoji(ctx, f"attribute_{name}")
                    line += f"**{name}**: {value}"
                    lines.append(line)
                embed.add_field(name="> **AMULET**", value="\n".join(lines))
        embed.set_author(name=character, icon_url=profession.icon)
        try:
            file, = await asyncio.gather(task)
            embed.set_image(url=f"attachment://{file.filename}")
        except AttributeError:
            file = None
        embed.set_footer(
            text=("Colors of emojis represent item rarity. "
                  "Attributes aren't guaranteed to be accurate."),
            icon_url=self.bot.user.avatar_url)
        try:
            await ctx.send(embed=embed, file=file)
        except discord.Forbidden as e:
            await ctx.send(
                "Missing permission to embed links or to upload images")

    @character.command(name="gear")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_gear(self, ctx, *, character: str):
        """Displays the gear, attributes and build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        await self.display_gear(ctx, character)

    @character.command(name="pvpgear")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_pvpgear(self, ctx, *, character: str):
        """Displays the gear, attributes and build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        await self.display_gear(ctx, character, "pvp")

    @character.command(name="wvwgear")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_wvwgear(self, ctx, *, character: str):
        """Displays the gear, attributes and build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        await self.display_gear(ctx, character, "wvw")

    @character.command(name="birthdays")
    async def character_birthdays(self, ctx):
        """Lists days until the next birthday for each of your characters.

        Required permissions: characters
        """

        def suffix(year):
            if year == 1:
                return 'st'
            if year == 2:
                return 'nd'
            if year == 3:
                return 'rd'
            return "th"

        user = ctx.message.author
        await ctx.trigger_typing()
        try:
            doc = await self.fetch_key(user, ["characters"])
            characters = await self.get_all_characters(user)
        except APIError as e:
            return await self.error_handler(ctx, e)
        fields = {}
        for character in characters:
            age = datetime.datetime.utcnow() - character.created
            days = age.days
            floor = days // 365
            # finds days till next birthday
            days_left = 365 - (days - (365 * floor))
            next_bd = floor + 1
            fields.setdefault(next_bd, [])
            spec = await character.get_spec_info()
            fields[next_bd].append(("{} {}".format(
                self.get_emoji(ctx, spec["name"]), character.name), days_left))
        msg = "{.mention}, here are your upcoming birthdays:".format(user)
        embed = discord.Embed(
            title="Days until...", colour=await self.get_embed_color(ctx))
        embed.set_author(name=doc["account_name"], icon_url=user.avatar_url)
        for k, v in sorted(fields.items(), reverse=True, key=lambda k: k[0]):
            lines = [
                "{}: **{}**".format(*line)
                for line in sorted(v, key=lambda l: l[1])
            ]
            embed = embed_list_lines(embed, lines, "{}{} Birthday".format(
                k, suffix(k)))
        await ctx.send(msg, embed=embed)

    def readable_attribute(self, attribute_name):
        attribute_sub = re.sub(r"(\w)([A-Z])", r"\1 \2", attribute_name)
        attribute_sub = re.sub('Crit ', 'Critical ', attribute_sub)
        attribute_sub = re.sub('Healing', 'Healing Power', attribute_sub)
        attribute_sub = re.sub('defense', 'Armor', attribute_sub)
        return attribute_sub

    async def calculate_character_attributes(self, character):
        def search_lvl_to_increase(level: int, lvl_dict):
            for increase, lvl in lvl_dict.items():
                if lvl[0] <= level <= lvl[1]:
                    if level < 11:
                        return increase
                    elif level % 2 == 0:
                        return increase
                    else:
                        return 0

        def calc_base_lvl(level: int, acc_baselvl: int, lvl_dict):
            # Recursive call of search_lvl_to_increase
            # Calculating the base primary attributes depending on char lvl
            if level == 1:
                acc_baselvl += 37
                return acc_baselvl
            else:
                new_acc = acc_baselvl + search_lvl_to_increase(level, lvl_dict)
                new_lvl = level - 1
                return calc_base_lvl(new_lvl, new_acc, lvl_dict)

        def search_lvl_to_health(level: int, health_dict):
            for increase, lvl in health_dict.items():
                if lvl[0] <= level <= lvl[1]:
                    return increase

        def calc_base_health(level: int, acc_baselvl: int, health_dict):
            # Recursive call of search_lvl_to_health
            # Calculating the base health depending on char lvl
            if level == 1:
                acc_baselvl += search_lvl_to_health(level, health_dict)
                # Parse to int because of possible floats
                return int(acc_baselvl)
            else:
                new_acc = acc_baselvl + search_lvl_to_health(
                    level, health_dict)
                new_lvl = level - 1
                return calc_base_health(new_lvl, new_acc, health_dict)

        attr_list = [
            'defense', 'Power', 'Vitality', 'Precision', 'Toughness',
            'Critical Chance', 'Health', 'Concentration', 'Expertise',
            'BoonDuration', 'ConditionDamage', 'Ferocity', 'CritDamage',
            'Healing', 'ConditionDuration', 'AgonyResistance'
        ]
        percentage_list = [
            'Critical Chance', 'CritDamage', 'ConditionDuration',
            'BoonDuration'
        ]
        lvl_dict = {
            7: [2, 10],
            10: [11, 20],
            14: [21, 24],
            15: [25, 26],
            16: [27, 30],
            20: [31, 40],
            24: [41, 44],
            25: [45, 46],
            26: [47, 50],
            30: [51, 60],
            34: [61, 64],
            35: [65, 66],
            36: [67, 70],
            44: [71, 74],
            45: [75, 76],
            46: [77, 80]
        }
        health_group1 = {
            28: [1, 19],
            70: [20, 39],
            140: [40, 59],
            210: [60, 79],
            280: [80, 80]
        }
        health_group2 = {
            18: [1, 19],
            45: [20, 39],
            90: [40, 59],
            135: [60, 79],
            180: [80, 80]
        }
        health_group3 = {
            5: [1, 19],
            12.5: [20, 39],
            25: [40, 59],
            37.5: [60, 79],
            50: [80, 80]
        }

        profession_group = {
            "warrior": health_group1,
            "necromancer": health_group1,
            "revenant": health_group2,
            "engineer": health_group2,
            "ranger": health_group2,
            "mesmer": health_group2,
            "guardian": health_group3,
            "thief": health_group3,
            "elementalist": health_group3
        }

        ignore_list = [
            'HelmAquatic', 'WeaponAquaticA', 'WeaponAquaticB', 'WeaponB1',
            'WeaponB2', "Sickle", "Axe", "Pick"
        ]
        attr_dict = {key: 0 for (key) in attr_list}
        runes = {}
        level = character["level"]
        eq = character["equipment"]
        for piece in eq:
            item = await self.fetch_item(piece["id"])
            # Gear with selectable values
            if "stats" in piece:
                if piece["slot"] not in ignore_list:
                    attributes = piece["stats"]["attributes"]
                    for attribute in attributes:
                        attr_dict[attribute] += attributes[attribute]
            # Gear with static values, except harvesting tools
            elif "charges" not in piece:
                if piece["slot"] not in ignore_list:
                    if "infix_upgrade" in item["details"]:
                        attributes = item["details"]["infix_upgrade"][
                            "attributes"]
                        for attribute in attributes:
                            attr_dict[attribute["attribute"]] += attribute[
                                "modifier"]
            # Get armor rating
            if "defense" in item["details"]:
                if piece["slot"] not in ignore_list:
                    attr_dict['defense'] += item["details"]["defense"]
            # Mapping for old attribute names
            attr_dict["Concentration"] += attr_dict["BoonDuration"]
            attr_dict["Ferocity"] += attr_dict["CritDamage"]
            attr_dict["Expertise"] += attr_dict["ConditionDuration"]
            # Reset old mapped attributes
            attr_dict["BoonDuration"] = 0
            attr_dict["CritDamage"] = 0
            attr_dict["ConditionDuration"] = 0

        # Have to run again through eq, because attributes
        # from upgrades are named different
        # Get stats from item upgrades (runes ...)
        for piece in eq:
            if "upgrades" in piece:
                if piece["slot"] not in ignore_list:
                    upgrades = piece["upgrades"]
                    for upgrade in upgrades:
                        item_upgrade = await self.fetch_item(upgrade)
                        # Jewels and stuff
                        if "infix_upgrade" in item_upgrade["details"]:
                            attributes = item_upgrade["details"][
                                "infix_upgrade"]["attributes"]
                            for attribute in attributes:
                                attr_dict[attribute["attribute"]] += attribute[
                                    "modifier"]
                        # Runes
                        if item_upgrade["details"]["type"] == "Rune":
                            # Rune counter
                            if upgrade in runes:
                                runes[upgrade] += 1
                            else:
                                runes[upgrade] = 1
                        elif item_upgrade["details"]["type"] == "Sigil":
                            pattern_percentage = re.compile("^\+\d{1,}% ")
                            bonus = item_upgrade["details"]["infix_upgrade"][
                                "buff"]["description"]
                            if pattern_percentage.match(bonus):
                                modifier = re.sub(' .*$', '', bonus)
                                modifier = re.sub('\+', '', modifier)
                                modifier = re.sub('%', '', modifier)
                                attribute_name = bonus.title()
                                attribute_name = re.sub(
                                    ' Duration', 'Duration', attribute_name)
                                attribute_name = re.sub('Duration.*', 'Duration', attribute_name)
                                attribute_name = re.sub(
                                    ' Chance', 'Chance', attribute_name)
                                attribute_name = re.sub('Chance.*', 'Chance', attribute_name)
                                attribute_name = re.sub(
                                    '^.* ', '', attribute_name)
                                attribute_name = re.sub(
                                    '\.', '', attribute_name)
                                if attribute_name in attr_dict:
                                    attr_dict[attribute_name] += int(modifier)
            # Infusions
            if "infusions" in piece:
                if piece["slot"] not in ignore_list:
                    infusions = piece["infusions"]
                    for infusion in infusions:
                        item_infusion = await self.fetch_item(infusion)
                        if "infix_upgrade" in item_infusion["details"]:
                            attributes = item_infusion["details"][
                                "infix_upgrade"]["attributes"]
                            for attribute in attributes:
                                if attribute["attribute"] == "BoonDuration":
                                    attribute["attribute"] = "Concentration"
                                if attribute["attribute"] == "ConditionDuration":
                                    attribute["attribute"] = "Expertise"
                                attr_dict[attribute["attribute"]] += attribute[
                                    "modifier"]

        for rune, runecount in runes.items():
            rune_item = await self.fetch_item(rune)
            bonuses = rune_item["details"]["bonuses"]
            count = 0
            for bonus in bonuses:
                if count < runecount:
                    pattern_single = re.compile("^\+\d{1,} ")
                    pattern_all_stats = re.compile(".* [s,S]tats$")
                    pattern_percentage = re.compile("^\+\d{1,}% ")
                    # Regex deciding if it's a stat
                    if pattern_all_stats.match(bonus):
                        modifier = re.sub(' .*$', '', bonus)
                        modifier = re.sub('\+', '', modifier)
                        attr_dict["Power"] += int(modifier)
                        attr_dict["Vitality"] += int(modifier)
                        attr_dict["Toughness"] += int(modifier)
                        attr_dict["Precision"] += int(modifier)
                        attr_dict["Ferocity"] += int(modifier)
                        attr_dict["Healing"] += int(modifier)
                        attr_dict["ConditionDamage"] += int(modifier)
                    elif pattern_single.match(bonus):
                        # Regex deciding the attribute name + modifier
                        modifier = re.sub(' .*$', '', bonus)
                        modifier = re.sub('\+', '', modifier)
                        attribute_name = re.sub(' Damage', 'Damage', bonus)
                        attribute_name = re.sub('Damage.*', 'Damage', attribute_name)
                        attribute_name = re.sub('\+\d{1,} ', '', attribute_name)
                        attribute_name = re.sub(';.*', '', attribute_name)
                        if attribute_name in attr_dict:
                            attr_dict[attribute_name] += int(modifier)
                    elif pattern_percentage.match(bonus):
                        modifier = re.sub(' .*$', '', bonus)
                        modifier = re.sub('\+', '', modifier)
                        modifier = re.sub('%', '', modifier)
                        attribute_name = re.sub(' Duration', 'Duration', bonus)
                        attribute_name = re.sub('Duration.*', 'Duration', attribute_name)
                        attribute_name = re.sub('^.* ', '', attribute_name)
                        if attribute_name in attr_dict:
                            attr_dict[attribute_name] += int(modifier)
                    # Amount of runes equipped
                    count += 1

        # Calculate base value depending on char level
        basevalue = calc_base_lvl(level, 0, lvl_dict)
        attr_dict["Power"] += basevalue
        attr_dict["Vitality"] += basevalue
        attr_dict["Toughness"] += basevalue
        attr_dict["Precision"] += basevalue
        # Calculate derivative attributes
        # Reset to default after mapped to new attribute name
        attr_dict["CritDamage"] += round(150 + attr_dict["Ferocity"] / 15, 2)
        if attr_dict["CritDamage"] == 0:
            attr_dict["CritDamage"] = int(attr_dict["CritDamage"])
        attr_dict["BoonDuration"] += round(attr_dict["Concentration"] / 15, 2)
        if attr_dict["BoonDuration"] == 0:
            attr_dict["BoonDuration"] = int(attr_dict["BoonDuration"])
        attr_dict["ConditionDuration"] += round(attr_dict["Expertise"] / 15, 2)
        if attr_dict["ConditionDuration"] == 0:
            attr_dict["ConditionDuration"] = int(
                attr_dict["ConditionDuration"])
        # Base value of 1000 on lvl 80 doesn't get calculated,
        # if below lvl 80 dont subtract it
        if attr_dict["Precision"] < 1000:
            base_prec = 0
        else:
            base_prec = 1000
        attr_dict["Critical Chance"] = round(
            4 + ((attr_dict["Precision"] - base_prec) / 21), 2)
        attr_dict["defense"] += attr_dict["Toughness"]

        # Calculate base health
        attr_dict["Health"] = calc_base_health(
            level, 0, profession_group[character["profession"].lower()])
        attr_dict["Health"] += attr_dict["Vitality"] * 10

        ordered_list = ('Power', 'Toughness', 'Vitality', 'Precision',
                        'Ferocity', 'ConditionDamage', 'Expertise',
                        'Concentration', 'AgonyResistance', 'defense',
                        'Health', 'Critical Chance', 'CritDamage', 'Healing',
                        'ConditionDuration', 'BoonDuration')
        # First one is not inline for layout purpose
        output = {}
        for attribute in ordered_list:
            if attribute in percentage_list:
                attr_dict[attribute] = '{0}%'.format(round(attr_dict[attribute]),2)
            attribute_sub = self.readable_attribute(attribute)
            output[attribute_sub.title()] = attr_dict[attribute]
        return output

    @character.command(name="attributes", hidden=True)
    @commands.cooldown(1, 10, BucketType.user)
    async def character_attributes(self, ctx, *, character: str):
        await ctx.invoke(self.character_gear, character=character)

    @character.command(name="build", aliases=["pvebuild"], hidden=True)
    @commands.cooldown(1, 10, BucketType.user)
    async def character_build(self, ctx, *, character: str):
        """Displays the build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        await ctx.invoke(self.character_gear, character=character)

    @character.command(name="pvpbuild", hidden=True)
    @commands.cooldown(1, 10, BucketType.user)
    async def character_pvpbuild(self, ctx, *, character: str):
        """Displays the build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        await ctx.invoke(self.character_pvpgear, character=character)

    @character.command(name="wvwbuild", hidden=True)
    @commands.cooldown(1, 10, BucketType.user)
    async def character_wvwbuild(self, ctx, *, character: str):
        """Displays the build of given character
        You must be the owner of the character.

        Required permissions: characters
        """
        await ctx.invoke(self.character_wvwgear, character=character)

    async def build_embed(self, results, mode):
        profession = await self.get_profession(results, mode=mode)
        level = results["level"]
        specializations = results["specializations"][mode]
        embed = discord.Embed(
            title="{} build".format(mode.upper()), color=profession.color)
        embed.set_author(name=results["name"])
        for spec in specializations:
            if spec is None:
                continue
            spec_doc = await self.db.specializations.find_one({
                "_id": spec["id"]
            })
            spec_name = spec_doc["name"]
            traits = []
            for trait in spec["traits"]:
                if trait is None:
                    continue
                trait_doc = await self.db.traits.find_one({"_id": trait})
                tier = trait_doc["tier"] - 1
                trait_index = spec_doc["major_traits"].index(trait)
                trait_index = 1 + trait_index - tier * 3
                traits.append("{} ({})".format(trait_doc["name"], trait_index))
            if traits:
                embed.add_field(
                    name=spec_name, value="\n".join(traits), inline=False)
            embed.set_footer(
                text="A level {} {} ".format(level, profession.name.lower()),
                icon_url=profession.icon)
        return embed

    @character.command(name="togglepublic")
    @commands.cooldown(1, 1, BucketType.user)
    async def character_togglepublic(self, ctx, *, character_or_all: str):
        """Toggle your character's (or all of them) status to public

        Public characters can have their gear and build checked by anyone.
        The rest is still private.

        Required permissions: characters
        """
        character = character_or_all.title()
        user = ctx.author
        await ctx.trigger_typing()
        try:
            key = await self.fetch_key(user, ["characters"])
            results = await self.call_api("characters", key=key["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        if character not in results and character != "All":
            return await ctx.send("Invalid character name")
        characters = [character] if character != "All" else results
        output = []
        for char in characters:
            doc = await self.db.characters.find_one({"name": char})
            if doc:
                await self.db.characters.delete_one({"name": char})
                output.append(char + " is now private")
            else:
                await self.db.characters.insert_one({
                    "name":
                    char,
                    "owner":
                    user.id,
                    "owner_acc_name":
                    key["account_name"]
                })
                output.append(char + " is now public")
        await ctx.send("Character status successfully changed. Anyone can "
                       "check public characters gear and build - the rest is "
                       "still private. To make character private "
                       "again, type the same command.")
        if character == "All":
            await user.send("\n".join(output))

    @character.command(name="crafting")
    @commands.cooldown(1, 10, BucketType.user)
    async def character_crafting(self, ctx):
        """Displays your characters and their crafting level"""
        endpoint = "characters?page=0&page_size=200"
        await ctx.trigger_typing()
        try:
            doc = await self.fetch_key(ctx.author, ["characters"])
            characters = await self.call_api(endpoint, key=doc["key"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description='Crafting overview',
            colour=await self.get_embed_color(ctx))
        data.set_author(
            name=doc["account_name"], icon_url=ctx.author.avatar_url)
        counter = 0
        for character in characters:
            if counter == 25:
                break
            craft_list = self.get_crafting(character)
            if craft_list:
                data.add_field(
                    name=character["name"], value="\n".join(craft_list))
                counter += 1
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    @commands.group(case_insensitive=True)
    async def sab(self, ctx):
        """Super Adventure Box commands"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @sab.command(name="unlocks")
    @commands.cooldown(1, 10, BucketType.user)
    async def sab_unlocks(self, ctx, *, character):
        """Displays missing SAB unlocks for specified character"""

        def readable(_id):
            return _id.replace("_", " ").title()

        user = ctx.author
        scopes = ["characters", "progression"]
        character = character.title().replace(" ", "%20")
        endpoint = "characters/{}/sab".format(character)
        try:
            results = await self.call_api(endpoint, user, scopes)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        unlocked = [u["name"] for u in results["unlocks"]]
        missing = [
            readable(u) for u in self.gamedata["sab"]["unlocks"]
            if u not in unlocked
        ]
        if missing:
            return await ctx.send(
                "This character is missing the following SAB "
                "upgrades:\n```fix\n{}\n```".format("\n".join(missing)))
        await ctx.send("You have unlocked all the upgrades on "
                       "this character! Congratulations!")

    @sab.command(name="zones")
    @commands.cooldown(1, 10, BucketType.user)
    async def sab_zones(self, ctx, *, character):
        """Displays missing SAB zones for specified character"""

        def missing_zones(zones):
            modes = ["infantile", "normal", "tribulation"]
            worlds = 1, 2
            number_of_zones = 3
            [z.pop("id") for z in zones]
            missing = []
            for world in worlds:
                for mode in modes:
                    for zone in range(1, number_of_zones + 1):
                        zone_dict = {
                            "world": world,
                            "zone": zone,
                            "mode": mode
                        }
                        if zone_dict not in zones:
                            missing.append("W{}Z{} {} mode".format(
                                world, zone, mode.title()))
            return missing

        user = ctx.author
        scopes = ["characters", "progression"]
        character = character.title().replace(" ", "%20")
        endpoint = "characters/{}/sab".format(character)
        try:
            results = await self.call_api(endpoint, user, scopes)
        except APINotFound:
            return await ctx.send("Invalid character name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        missing = missing_zones(results["zones"])
        if missing:
            return await ctx.send(
                "This character is missing the following SAB "
                "zones:\n```fix\n{}\n```".format("\n".join(missing)))
        await ctx.send("You have unlocked all zones on "
                       "this character! Congratulations!")

    async def get_all_characters(self, user, scopes=None):
        endpoint = "characters?page=0&page_size=200"
        results = await self.call_api(endpoint, user, scopes)
        return [Character(self, c) for c in results]

    async def get_character(self, ctx, character):
        character = character.title()
        endpoint = "characters/" + character.replace(" ", "%20")
        try:
            results = await self.call_api(endpoint, ctx.author,
                                          ["characters", "builds"])
        except APINotFound:
            results = await self.get_public_character(character)
            if not results:
                raise APINotFound
        return results

    async def get_public_character(self, character):
        character = character.title()
        endpoint = "characters/" + character.replace(" ", "%20")
        doc = await self.db.characters.find_one({"name": character})
        if doc:
            user = await self.bot.fetch_user(doc["owner"])
            try:
                return await self.call_api(endpoint, user)
            except APIError:
                return None
        return None

    def get_crafting(self, character):
        craft_list = []
        for crafting in character["crafting"]:
            rating = crafting["rating"]
            discipline = crafting["discipline"]
            craft_list.append("Level {} {}".format(rating, discipline))
        return craft_list

    async def get_profession(self, character, *, mode="pve"):
        async def get_elite_spec(character):
            spec = character["specializations"][mode][2]
            if spec:
                spec = await self.db.specializations.find_one({
                    "_id": spec["id"]
                })
                if spec is None or not spec["elite"]:
                    return None
                return spec["name"]
            return None

        def get_icon_url(prof_name):
            base_url = ("https://api.gw2bot.info/"
                        "resources/professions/{}_icon.png")
            return base_url.format(prof_name.replace(" ", "_").lower())

        Profession = collections.namedtuple("Profession",
                                            ["name", "icon", "color"])
        color = discord.Color(
            int(
                self.gamedata["professions"][character["profession"].lower()]
                ["color"], 0))
        name = await get_elite_spec(character) or character["profession"]
        icon = get_icon_url(name)
        return Profession(name, icon, color)

    def get_profession_icon(self, prof_name):
        url = ("https://api.gw2bot.info/" "resources/professions/{}_icon.png")
        return url.format(prof_name.replace(" ", "_").lower())
