import re
from typing import Any, Dict, List


class CharactersService:
    def __init__(self, api_client, repo=None):
        self.api = api_client
        self.repo = repo

    async def get_all_characters(self, *, key: str) -> List[Dict[str, Any]]:
        endpoint = "characters?page=0&page_size=200"
        return await self.api.get(
            endpoint, key=key, schema_string="2021-07-15T13:00:00.000Z"
        )

    @staticmethod
    def total_play_time(characters: List[Dict[str, Any]]) -> int:
        return sum(c.get("age", 0) for c in characters)

    # Thin repo wrappers
    async def fetch_item(self, item_id: int) -> Dict[str, Any] | None:
        if not self.repo:
            return None
        return await self.repo.get_item(item_id)

    async def fetch_stat_name(self, stat_id: int) -> str:
        if not self.repo:
            return ""
        return await self.repo.get_stat_name(stat_id)

    # General helpers
    @staticmethod
    def format_age(age: int, *, short: bool = False) -> str:
        hours, seconds = divmod(age, 3600)
        minutes = round(seconds / 60)
        h_str = "h" if short else " hours"
        m_str = "m" if short else " minutes"
        if hours:
            return f"{hours}{h_str} {minutes}{m_str}"
        return f"{minutes}{m_str}"

    @staticmethod
    def get_crafting(character: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        for c in character.get("crafting", []) or []:
            rating = c.get("rating")
            discipline = c.get("discipline")
            if rating is not None and discipline:
                out.append(f"Level {rating} {discipline}")
        return out

    async def get_title(self, title_id: int) -> str:
        if not self.repo:
            return ""
        return await self.repo.get_title(title_id)

    async def get_profession_by_character(
        self, character: Dict[str, Any], gamedata
    ) -> Dict[str, Any]:
        # Determine active tab
        active_tab = None
        for tab in character.get("build_tabs", []) or []:
            if tab.get("is_active"):
                active_tab = tab
                break
        specs = (active_tab or {}).get("build", {}).get("specializations", [])
        specializations = []
        if self.repo:
            for spec in specs:
                spec_id = spec if isinstance(spec, int) else spec.get("id")
                spec_doc = await self.repo.get_specialization(spec_id)
                if spec_doc:
                    specializations.append(spec_doc)

        # Choose display name: elite spec (last) if elite, else base profession
        def elite_spec_name():
            try:
                spec = specializations[-1]
            except IndexError:
                return None
            if spec and spec.get("elite"):
                return spec.get("name")
            return None

        prof_key = (character.get("profession") or "").lower()
        display_name = elite_spec_name() or character.get("profession", "")
        # Icon URL pattern
        icon_name = (display_name or "").replace(" ", "_").lower()
        icon = f"https://resources.gw2bot.info/professions/{icon_name}_icon.png"
        # Color from gamedata
        try:
            color_hex = gamedata["professions"][prof_key]["color"]
            color = int(color_hex, 16)
        except Exception:
            color = 0x000000
        return {"name": str(display_name).title(), "icon": icon, "color": color}

    async def get_profession(
        self,
        profession: str,
        specializations: List[Dict[str, Any]],
        gamedata,
    ) -> Dict[str, Any]:
        """Return profession presentation from base profession and specialization docs.

        Inputs:
        - profession: Base profession name (e.g., "Guardian").
        - specializations: List of specialization documents; last may be elite.
        - gamedata: Mapping that includes professions color data.

        Output dict keys: name (title-cased), icon (URL), color (int RGB).
        """
        # Choose display name: elite spec (last) if elite, else base profession
        name = profession
        try:
            last_spec = specializations[-1]
            if last_spec and last_spec.get("elite"):
                name = last_spec.get("name", profession)
        except IndexError:
            pass

        # Icon URL pattern
        icon_name = (name or "").replace(" ", "_").lower()
        icon = f"https://resources.gw2bot.info/professions/{icon_name}_icon.png"

        # Color from gamedata
        try:
            prof_key = (profession or "").lower()
            color_hex = gamedata["professions"][prof_key]["color"]
            color = int(color_hex, 16)
        except Exception:
            color = 0x000000

        return {"name": str(name).title(), "icon": icon, "color": color}

    async def get_character_by_key(self, *, name: str, key: str) -> Dict[str, Any]:
        safe = name.title().replace(" ", "%20")
        endpoint = f"characters/{safe}"
        return await self.api.get(
            endpoint, key=key, schema_string="2021-07-15T13:00:00.000Z"
        )

    # Helpers extracted from mixin
    @staticmethod
    def readable_attribute(attribute_name: str) -> str:
        attribute_sub = re.sub(r"(\w)([A-Z])", r"\1 \2", attribute_name)
        attribute_sub = re.sub("Crit ", "Critical ", attribute_sub)
        attribute_sub = re.sub("Healing", "Healing Power", attribute_sub)
        attribute_sub = re.sub("defense", "Armor", attribute_sub)
        return attribute_sub

    async def calculate_attributes(
        self, character: Dict[str, Any], eq: List[Dict[str, Any]]
    ):
        # Adapted from CharactersMixin.calculate_character_attributes
        def search_lvl_to_increase(level: int, lvl_dict: Dict[int, List[int]]):
            for increase, rng in lvl_dict.items():
                if rng[0] <= level <= rng[1]:
                    if level < 11:
                        return increase
                    return increase if level % 2 == 0 else 0

        def calc_base_lvl(level: int, acc: int, lvl_dict: Dict[int, List[int]]):
            if level == 1:
                return acc + 37
            inc = search_lvl_to_increase(level, lvl_dict) or 0
            return calc_base_lvl(level - 1, acc + inc, lvl_dict)

        def search_lvl_to_health(level: int, health_dict: Dict[int, List[int]]):
            for increase, rng in health_dict.items():
                if rng[0] <= level <= rng[1]:
                    return increase

        def calc_base_health(level: int, acc: int, health_dict: Dict[int, List[int]]):
            if level == 1:
                inc = search_lvl_to_health(level, health_dict) or 0
                return int(acc + inc)
            inc = search_lvl_to_health(level, health_dict) or 0
            return calc_base_health(level - 1, acc + inc, health_dict)

        attr_list = [
            "defense",
            "Power",
            "Vitality",
            "Precision",
            "Toughness",
            "Critical Chance",
            "Health",
            "Concentration",
            "Expertise",
            "BoonDuration",
            "ConditionDamage",
            "Ferocity",
            "CritDamage",
            "Healing",
            "ConditionDuration",
            "AgonyResistance",
        ]
        percentage_list = [
            "Critical Chance",
            "CritDamage",
            "ConditionDuration",
            "BoonDuration",
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
            46: [77, 80],
        }
        health_group1 = {
            28: [1, 19],
            70: [20, 39],
            140: [40, 59],
            210: [60, 79],
            280: [80, 80],
        }
        health_group2 = {
            18: [1, 19],
            45: [20, 39],
            90: [40, 59],
            135: [60, 79],
            180: [80, 80],
        }
        health_group3 = {
            5: [1, 19],
            12.5: [20, 39],
            25: [40, 59],
            37.5: [60, 79],
            50: [80, 80],
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
            "elementalist": health_group3,
        }

        ignore_list = [
            "HelmAquatic",
            "WeaponAquaticA",
            "WeaponAquaticB",
            "WeaponB1",
            "WeaponB2",
            "Sickle",
            "Axe",
            "Pick",
        ]
        attr_dict = {key: 0 for (key) in attr_list}
        runes = {}
        level = character["level"]
        for piece in eq:
            item = await self.fetch_item(piece["id"]) or {}
            if "stats" in piece:
                if piece["slot"] not in ignore_list:
                    attributes = piece["stats"].get("attributes", {})
                    for attribute in attributes:
                        attr_dict[attribute] += attributes[attribute]
            elif "charges" not in piece:
                if piece["slot"] not in ignore_list:
                    details = item.get("details", {})
                    if "infix_upgrade" in details:
                        attributes = details["infix_upgrade"].get("attributes", [])
                        for attribute in attributes:
                            k = attribute["attribute"]
                            attr_dict[k] += int(attribute["modifier"])
            if "details" in item and "defense" in item["details"]:
                if piece["slot"] not in ignore_list:
                    attr_dict["defense"] += int(item["details"]["defense"])
            # map old names
            attr_dict["Concentration"] += attr_dict["BoonDuration"]
            attr_dict["Ferocity"] += attr_dict["CritDamage"]
            attr_dict["Expertise"] += attr_dict["ConditionDuration"]
            attr_dict["BoonDuration"] = 0
            attr_dict["CritDamage"] = 0
            attr_dict["ConditionDuration"] = 0

        for piece in eq:
            if "upgrades" in piece:
                if piece["slot"] not in ignore_list:
                    upgrades = piece["upgrades"]
                    for upgrade in upgrades:
                        item_upgrade = await self.fetch_item(upgrade) or {}
                        details = item_upgrade.get("details", {})
                        if "infix_upgrade" in details:
                            attributes = details["infix_upgrade"].get("attributes", [])
                            for attribute in attributes:
                                k = attribute["attribute"]
                                attr_dict[k] += int(attribute["modifier"])
                        if details.get("type") == "Rune":
                            runes[upgrade] = runes.get(upgrade, 0) + 1
                        elif details.get("type") == "Sigil":
                            pattern_percentage = re.compile(r"^\+\d{1,}% ")
                            buff = details.get("infix_upgrade", {}).get("buff", {})
                            bonus = buff.get("description", "")
                            if pattern_percentage.match(bonus):
                                modifier = re.sub(r" .*$", "", bonus)
                                modifier = re.sub(r"\+", "", modifier)
                                modifier = re.sub(r"%", "", modifier)
                                attribute_name = bonus.title()
                                attribute_name = re.sub(
                                    " Duration", "Duration", attribute_name
                                )
                                attribute_name = re.sub(
                                    "Duration.*", "Duration", attribute_name
                                )
                                attribute_name = re.sub(
                                    " Chance", "Chance", attribute_name
                                )
                                attribute_name = re.sub(
                                    "Chance.*", "Chance", attribute_name
                                )
                                attribute_name = re.sub(r"^.* ", "", attribute_name)
                                attribute_name = re.sub(r"\.", "", attribute_name)
                                if attribute_name in attr_dict:
                                    attr_dict[attribute_name] += int(modifier)
            if "infusions" in piece:
                if piece["slot"] not in ignore_list:
                    infusions = piece["infusions"]
                    for infusion in infusions:
                        item_infusion = await self.fetch_item(infusion) or {}
                        details = item_infusion.get("details", {})
                        if "infix_upgrade" in details:
                            attributes = details["infix_upgrade"].get("attributes", [])
                            for attribute in attributes:
                                if attribute["attribute"] == "BoonDuration":
                                    attribute["attribute"] = "Concentration"
                                if attribute["attribute"] == "ConditionDuration":
                                    attribute["attribute"] = "Expertise"
                                k2 = attribute["attribute"]
                                attr_dict[k2] += int(attribute["modifier"])

        for rune, runecount in runes.items():
            rune_item = await self.fetch_item(rune) or {}
            details = rune_item.get("details", {})
            bonuses = details.get("bonuses", [])
            count = 0
            # patterns for rune bonus parsing
            pattern_single = re.compile(r"^\+\d{1,} ")
            pattern_all_stats = re.compile(r".* [s,S]tats$")
            pattern_percentage = re.compile(r"^\+\d{1,}% ")
            for bonus in bonuses:
                if count < runecount:
                    if pattern_all_stats.match(bonus):
                        modifier = re.sub(r" .*$", "", bonus)
                        modifier = re.sub(r"\+", "", modifier)
                        for k in [
                            "Power",
                            "Vitality",
                            "Toughness",
                            "Precision",
                            "Ferocity",
                            "Healing",
                            "ConditionDamage",
                        ]:
                            attr_dict[k] += int(modifier)
                    elif pattern_single.match(bonus):
                        modifier = re.sub(r" .*$", "", bonus)
                        modifier = re.sub(r"\+", "", modifier)
                        attribute_name = re.sub(" Damage", "Damage", bonus)
                        attribute_name = re.sub("Damage.*", "Damage", attribute_name)
                        attribute_name = re.sub(r"\+\d{1,} ", "", attribute_name)
                        attribute_name = re.sub(";.*", "", attribute_name)
                        if attribute_name in attr_dict:
                            attr_dict[attribute_name] += int(modifier)
                    elif pattern_percentage.match(bonus):
                        modifier = re.sub(r" .*$", "", bonus)
                        modifier = re.sub(r"\+", "", modifier)
                        modifier = re.sub(r"%", "", modifier)
                        attribute_name = re.sub(" Duration", "Duration", bonus)
                        attribute_name = re.sub(
                            "Duration.*", "Duration", attribute_name
                        )
                        attribute_name = re.sub(r"^.* ", "", attribute_name)
                        if attribute_name in attr_dict:
                            attr_dict[attribute_name] += int(modifier)
                    count += 1

        basevalue = calc_base_lvl(level, 0, lvl_dict)
        attr_dict["Power"] += basevalue
        attr_dict["Vitality"] += basevalue
        attr_dict["Toughness"] += basevalue
        attr_dict["Precision"] += basevalue
        attr_dict["CritDamage"] += int(round(150 + attr_dict["Ferocity"] / 15, 2))
        attr_dict["BoonDuration"] += int(round(attr_dict["Concentration"] / 15, 2))
        attr_dict["ConditionDuration"] += int(round(attr_dict["Expertise"] / 15, 2))
        base_prec = 0 if attr_dict["Precision"] < 1000 else 1000
        crit = int(round(4 + ((attr_dict["Precision"] - base_prec) / 21), 2))
        attr_dict["Critical Chance"] = crit
        attr_dict["defense"] += attr_dict["Toughness"]

        prof = character["profession"].lower()
        attr_dict["Health"] = calc_base_health(level, 0, profession_group[prof])
        attr_dict["Health"] += attr_dict["Vitality"] * 10

        ordered_list = (
            "Power",
            "Toughness",
            "Vitality",
            "Precision",
            "Ferocity",
            "ConditionDamage",
            "Expertise",
            "Concentration",
            "AgonyResistance",
            "defense",
            "Health",
            "Critical Chance",
            "CritDamage",
            "Healing",
            "ConditionDuration",
            "BoonDuration",
        )
        output = {}
        for attribute in ordered_list:
            if attribute in percentage_list:
                output_name = self.readable_attribute(attribute).title()
                output[output_name] = f"{int(round(attr_dict[attribute]))}%"
            else:
                output_name = self.readable_attribute(attribute).title()
                output[output_name] = attr_dict[attribute]
        return output
