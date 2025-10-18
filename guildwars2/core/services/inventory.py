from __future__ import annotations

from collections import defaultdict
from typing import Any, DefaultDict, Dict, Iterable, List, Tuple, cast


class InventoryService:
    """Service for inventory and item-location related operations.

    This is a Discord-free port of the old AccountMixin.find_items_in_account
    so other layers (adapters, mixins) can reuse it without duplicating logic.
    """

    def __init__(self, api_client):
        self.api = api_client

    async def find_items_in_account(
        self,
        *,
        key: str,
        item_ids: Iterable[int],
        doc: Dict[str, Any] | None = None,
        flatten: bool = False,
        search: bool = False,
        results: Tuple[Any, Any, Any, Any] | None = None,
    ):
        """Search account storages and characters for specific items.

        Inputs:
        - key: API key with `inventories` and `characters` scopes.
        - item_ids: Iterable of item ids to search.
        - doc: Optional account document (used for permissions for TP delivery check).
        - flatten: If True, collapse counts across item ids into a single mapping
                   of location -> count. Otherwise returns per-item mapping.
        - search: If True, track [inventory_count, equipped_count] per location.
        - results: Optional tuple (bank, shared, materials, characters) to reuse
                   pre-fetched API results.

        Output:
        - If flatten is False: {item_id: {location: count or [inv, gear]}}
        - If flatten is True: {location: total_count or [inv, gear]}
        """

        item_ids = list(item_ids)

        if results is None:
            endpoints = (
                "account/bank",
                "account/inventory",
                "account/materials",
                "characters?page=0&page_size=200",
            )
            bank, shared, materials, characters = await self.api.get_many(
                endpoints, key=key, schema_string="2021-07-15T13:00:00.000Z"
            )
        else:
            bank, shared, materials, characters = results

        spaces = {"bank": bank, "shared": shared, "material storage": materials}
        legendary_armory_item_ids: set[int] = set()

        if search:
            counts: Dict[int, DefaultDict[str, Any]] = {
                item_id: defaultdict(lambda: [0, 0]) for item_id in item_ids
            }
        else:
            counts = {item_id: defaultdict(int) for item_id in item_ids}

        def get_amount(slot: Dict[str, Any] | None, item_id: int) -> int:
            def count_upgrades(slots: List[int] | None) -> int:
                return sum(1 for i in (slots or []) if i == item_id)

            if not slot:
                return 0
            if slot.get("id") == item_id:
                return int(slot.get("count", 1))
            if "infusions" in slot:
                infusions_sum = count_upgrades(cast(List[int], slot["infusions"]))
                if infusions_sum:
                    return infusions_sum
            if "upgrades" in slot:
                upgrades_sum = count_upgrades(cast(List[int], slot["upgrades"]))
                if upgrades_sum:
                    return upgrades_sum
            return 0

        def amounts_in_space(space, name: str, geared: bool):
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
            for tab in character.get("equipment_tabs", []) or []:
                amounts_in_space(tab.get("equipment", []), character.get("name"), True)

        # TP delivery (requires tradingpost permission)
        try:
            if doc and "tradingpost" in (doc.get("permissions", []) or []):
                result = await self.api.get("commerce/delivery", key=key)
                delivery = result.get("items", [])
                amounts_in_space(delivery, "TP delivery", False)
        except Exception:
            # Swallow API errors to avoid failing the whole search
            pass

        if flatten:
            if search:
                flattened: Dict[str, Any] = defaultdict(lambda: [0, 0])
            else:
                flattened = defaultdict(int)  # type: ignore[assignment]
            for count_dict in counts.values():
                for k, v in count_dict.items():
                    if search and isinstance(v, list):
                        lst = cast(List[int], flattened[k])
                        lst[0] += v[0]
                        lst[1] += v[1]
                    else:
                        flattened[k] += v
            return flattened

        return counts
