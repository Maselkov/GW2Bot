"""The /character gear attribute panel."""
import pytest

import subject

ORDER = [
    "Power", "Toughness", "Vitality", "Precision", "Ferocity", "Condition Damage", "Expertise",
    "Concentration", "Agony Resistance", "Armor", "Health", "Critical Chance", "Critical Damage",
    "Healing Power", "Condition Duration", "Boon Duration",
]


def naked(**changes):
    """The panel of a level 80 character with nothing equipped."""
    panel = {
        "Power": 1000, "Toughness": 1000, "Vitality": 1000, "Precision": 1000, "Ferocity": 0,
        "Condition Damage": 0, "Expertise": 0, "Concentration": 0, "Agony Resistance": 0, "Armor": 1000,
        "Health": 15922, "Critical Chance": "4%", "Critical Damage": "150%", "Healing Power": 0,
        "Condition Duration": "0%", "Boon Duration": "0%",
    }
    return {**panel, **changes}


def item(item_id, *, item_type="Armor", rarity="Ascended", attributes=None, defense=None, **details):
    """A cached item document; `attributes` are its fixed stats."""
    doc_details = {"type": item_type, **details}
    if attributes:
        doc_details["infix_upgrade"] = {
            "id": 1, "attributes": [{"attribute": a, "modifier": m} for a, m in attributes.items()],
        }
    if defense is not None:
        doc_details["defense"] = defense
    return {"_id": item_id, "name": f"Item {item_id}", "rarity": rarity, "details": doc_details}


def rune(item_id, *bonuses):
    return {"_id": item_id, "name": f"Rune {item_id}", "rarity": "Exotic",
            "details": {"type": "Rune", "bonuses": list(bonuses)}}


def sigil(item_id, description):
    return {"_id": item_id, "name": f"Sigil {item_id}", "rarity": "Exotic",
            "details": {"type": "Sigil", "infix_upgrade": {"id": 1, "attributes": [],
                                                           "buff": {"description": description}}}}


ARMOR = item(100, defense=0)


async def attributes(equipment, items=(), level=80, profession="Ranger"):
    return await subject.character_attributes(level, profession, equipment, [ARMOR, *items])


# --- Base values -------------------------------------------------------------------


async def test_nothing_equipped():
    panel = await attributes([])
    assert list(panel) == ORDER
    assert panel == naked()


@pytest.mark.parametrize(
    "profession, health",
    [
        # 9212 / 5922 / 1645 base health, plus 10 per Vitality
        ("Warrior", 19212), ("Necromancer", 19212),
        ("Revenant", 15922), ("Engineer", 15922), ("Ranger", 15922), ("Mesmer", 15922),
        ("Guardian", 11645), ("Thief", 11645), ("Elementalist", 11645),
    ],
)
async def test_health_by_profession(profession, health):
    panel = await attributes([], profession=profession)
    assert panel["Health"] == health


@pytest.mark.parametrize(
    "level, base, health",
    [
        (1, 37, 28 + 370),
        (10, 100, 280 + 1000),
        # Odd levels past 10 add nothing
        (39, 305, 28 * 19 + 70 * 20 + 3050),
        (40, 325, 28 * 19 + 70 * 20 + 140 + 3250),
    ],
)
async def test_base_values_by_level(level, base, health):
    panel = await attributes([], level=level, profession="Warrior")
    assert [panel[name] for name in ("Power", "Toughness", "Vitality", "Precision")] == [base] * 4
    assert panel["Armor"] == base
    assert panel["Health"] == health


# --- Equipment -------------------------------------------------------------------------


async def test_selectable_stats():
    # Berserker's helm with old attribute names, and its armor rating
    helm = {"id": 100, "slot": "Helm", "stats": {"id": 161, "attributes": {"Power": 63, "Precision": 45,
                                                                          "CritDamage": 45}}}
    items = [item(101, defense=97)]
    helm["id"] = 101
    panel = await attributes([helm], items)
    assert panel == naked(
        Power=1063, Precision=1045, Ferocity=45, Armor=1097,
        **{"Critical Damage": "153%", "Critical Chance": "6%"},
    )


async def test_fixed_stats_and_duration_attributes():
    ring = item(200, item_type="Trinket", attributes={"ConditionDamage": 126, "BoonDuration": 30,
                                                       "ConditionDuration": 45})
    panel = await attributes([{"id": 200, "slot": "Ring1"}], [ring])
    # Concentration and Expertise are 15 per 1% duration
    assert panel == naked(
        Concentration=30, Expertise=45,
        **{"Condition Damage": 126, "Boon Duration": "2%", "Condition Duration": "3%"},
    )


async def test_second_weapon_set_and_aquatic_gear_are_ignored():
    stats = {"id": 161, "attributes": {"Power": 100}}
    equipment = [
        {"id": 100, "slot": slot, "stats": stats}
        for slot in ("WeaponB1", "WeaponB2", "HelmAquatic", "WeaponAquaticA", "Sickle")
    ]
    assert await attributes(equipment) == naked()


async def test_first_weapon_set_counts():
    weapon = item(300, item_type="Weapon")
    panel = await attributes([{"id": 300, "slot": "WeaponA1", "stats": {"id": 1, "attributes": {"Power": 125}}}],
                             [weapon])
    assert panel["Power"] == 1125


async def test_harvesting_tools_without_stats():
    sickle = item(400, item_type="Gathering", attributes={"Power": 999})
    assert await attributes([{"id": 400, "slot": "Pick", "charges": 100}], [sickle]) == naked()


# --- Upgrades ------------------------------------------------------------------------------


async def test_rune_bonuses_count_with_the_runes_equipped():
    runes = rune(500, "+25 Power", "+35 Condition Damage", "+50 Power", "+65 Condition Damage",
                 "+100 Power", "+10% Condition Duration; +15% Burning Duration")
    two = [{"id": 100, "slot": slot, "upgrades": [500]} for slot in ("Helm", "Coat")]
    panel = await attributes(two, [runes])
    assert (panel["Power"], panel["Condition Damage"]) == (1025, 35)
    six = [{"id": 100, "slot": slot, "upgrades": [500]}
           for slot in ("Helm", "Shoulders", "Coat", "Gloves", "Leggings", "Boots")]
    panel = await attributes(six, [runes])
    assert (panel["Power"], panel["Condition Damage"], panel["Condition Duration"]) == (1175, 100, "10%")


async def test_rune_all_stats_bonus():
    runes = rune(501, "+25 All Stats")
    panel = await attributes([{"id": 100, "slot": "Helm", "upgrades": [501]}], [runes])
    assert panel == naked(
        Power=1025, Vitality=1025, Toughness=1025, Precision=1025, Ferocity=25, Armor=1025, Health=16172,
        **{"Healing Power": 25, "Condition Damage": 25, "Critical Damage": "152%", "Critical Chance": "5%"},
    )


async def test_sigil_duration_bonus():
    weapon = item(300, item_type="Weapon")
    malice = sigil(600, "+10% Condition Duration")
    panel = await attributes([{"id": 300, "slot": "WeaponA1", "upgrades": [600]}], [weapon, malice])
    assert panel["Condition Duration"] == "10%"


async def test_jewel_and_infusion_stats():
    amulet = item(201, item_type="Trinket")
    jewel = item(700, item_type="UpgradeComponent", attributes={"Power": 32, "Precision": 18})
    infusion = item(701, item_type="UpgradeComponent", attributes={"BoonDuration": 5, "AgonyResistance": 9})
    piece = {"id": 201, "slot": "Amulet", "upgrades": [700], "infusions": [701]}
    panel = await attributes([piece], [amulet, jewel, infusion])
    assert (panel["Power"], panel["Precision"]) == (1032, 1018)
    # Infusions' old attribute names are mapped too
    assert (panel["Concentration"], panel["Agony Resistance"]) == (5, 9)


async def test_upgrades_missing_from_the_cache_are_skipped():
    panel = await attributes([{"id": 100, "slot": "Helm", "upgrades": [999], "infusions": [998]}])
    assert panel == naked()


# --- Fixes -----------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="base critical chance is 4% instead of 5%, rounded to whole numbers")
async def test_critical_chance():
    assert (await attributes([]))["Critical Chance"] == "5%"
    helm = {"id": 100, "slot": "Helm", "stats": {"id": 1, "attributes": {"Precision": 45}}}
    # 5% plus 1% per 21 Precision over 1000
    assert (await attributes([helm]))["Critical Chance"] == "7.14%"


@pytest.mark.xfail(strict=True, reason="durations are rounded to whole percents")
async def test_durations_keep_two_decimals():
    helm = {"id": 100, "slot": "Helm", "stats": {"id": 1, "attributes": {"BoonDuration": 5, "Ferocity": 1}}}
    panel = await attributes([helm])
    assert (panel["Boon Duration"], panel["Critical Damage"]) == ("0.33%", "150.07%")


@pytest.mark.xfail(strict=True, reason="Healing Power rune bonuses are dropped")
async def test_rune_healing_power():
    runes = rune(502, "+25 Healing Power")
    panel = await attributes([{"id": 100, "slot": "Helm", "upgrades": [502]}], [runes])
    assert panel["Healing Power"] == 25


@pytest.mark.xfail(strict=True, reason="crashes on equipment that isn't cached")
async def test_equipment_missing_from_the_cache_is_skipped():
    panel = await attributes([{"id": 999, "slot": "Helm"}])
    assert panel == naked()
