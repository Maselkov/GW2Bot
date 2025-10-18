from collections import defaultdict

from .exceptions import APIError


class AccountMixin:
    async def find_items_in_account(
        self,
        user,
        item_ids,
        *,
        doc=None,
        flatten: bool = False,
        search: bool = False,
        results=None,
    ):
        from typing import Any, Dict, DefaultDict, List, cast

        if not doc:
            doc = await self.fetch_key(  # type: ignore[attr-defined]
                user, ["inventories", "characters"]
            )

        endpoints = [
            "account/bank",
            "account/inventory",
            "account/materials",
            "characters?page=0&page_size=200",
        ]
        if not results:
            results = await self.call_multiple(  # type: ignore[attr-defined]
                endpoints, key=doc["key"], schema_string="2021-07-15T13:00:00.000Z"
            )

        bank, shared, materials, characters = results
        spaces = {"bank": bank, "shared": shared, "material storage": materials}
        legendary_armory_item_ids = set()

        counts: Dict[int, DefaultDict[str, Any]]
        if search:
            counts = {item_id: defaultdict(lambda: [0, 0]) for item_id in item_ids}
        else:
            counts = {item_id: defaultdict(int) for item_id in item_ids}

        def get_amount(slot, item_id):
            def count_upgrades(slots):
                return sum(1 for i in slots if i == item_id)

            if not slot:
                return 0
            if slot.get("id") == item_id:
                return int(slot.get("count", 1))
            if "infusions" in slot:
                infusions_sum = count_upgrades(slot["infusions"])  # type: ignore[index]
                if infusions_sum:
                    return infusions_sum
            if "upgrades" in slot:
                upgrades_sum = count_upgrades(slot["upgrades"])  # type: ignore[index]
                if upgrades_sum:
                    return upgrades_sum
            return 0

        def amounts_in_space(space, name, geared):
            space_name = name
            for s in space or []:
                if geared and str(s.get("location", "")).endswith("LegendaryArmory"):
                    if s.get("id") in legendary_armory_item_ids:
                        continue
                    legendary_armory_item_ids.add(s.get("id"))
                    space_name = "legendary armory"
                for item_id in item_ids:
                    amt = get_amount(s, item_id)
                    if amt:
                        if search:
                            lst = cast(List[int], counts[item_id][space_name])
                            if geared:
                                lst[1] += amt
                            else:
                                lst[0] += amt
                        else:
                            prev = cast(int, counts[item_id][space_name])
                            counts[item_id][space_name] = prev + amt

        for name, space in spaces.items():
            amounts_in_space(space, name, False)
        for character in characters:
            amounts_in_space(character.get("bags", []), character.get("name"), False)
            bags = [
                bag.get("inventory") for bag in filter(None, character.get("bags", []))
            ]
            for bag in bags:
                amounts_in_space(bag, character.get("name"), False)
            for tab in character.get("equipment_tabs", []):
                amounts_in_space(tab.get("equipment", []), character.get("name"), True)

        try:
            if "tradingpost" in doc.get("permissions", []):
                result = await self.call_api(  # type: ignore[attr-defined]
                    "commerce/delivery", key=doc["key"]
                )
                delivery = result.get("items", [])
                amounts_in_space(delivery, "TP delivery", False)
        except APIError:
            pass

        if flatten:
            if search:
                flattened: Dict[str, Any] = defaultdict(lambda: [])
            else:
                flattened = defaultdict(int)  # type: ignore[assignment]
            for count_dict in counts.values():
                for k, v in count_dict.items():
                    flattened[k] += v
            return flattened

        return counts
