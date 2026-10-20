"""/character and /sab commands."""
import datetime
import time

import pytest

import subject

API = "https://api.guildwars2.com/v2/"
UTC = datetime.timezone.utc
ZWSP = "\u200b"


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


def build_tab(tab=1, elite=62, active=True, name="PvE"):
    return {"tab": tab, "is_active": active, "build": {
        "name": name, "profession": "Guardian",
        "specializations": [{"id": 42, "traits": [1, 2, 3]}, {"id": 16, "traits": [4, 5, 6]},
                            {"id": elite, "traits": [7, 8, 9]}],
        "skills": {"heal": None, "utilities": [None, None, None], "elite": None},
        "aquatic_skills": {"heal": None, "utilities": [None, None, None], "elite": None},
    }}


def character(name="Example Char", **details):
    """A synthetic /v2/characters/:id (never real account data)."""
    return {
        "name": name, "race": "Human", "gender": "Female", "profession": "Guardian", "level": 80,
        "guild": None, "age": 36000, "created": "2020-03-10T00:00:00Z", "deaths": 12,
        "crafting": [{"discipline": "Armorsmith", "rating": 500, "active": True},
                     {"discipline": "Chef", "rating": 150, "active": False}],
        "active_build_tab": 1, "build_tabs": [build_tab()],
        "equipment": [], "active_equipment_tab": 1, "equipment_tabs": [],
        **details,
    }


# Cached game data
SPECIALIZATIONS = [
    {"_id": 42, "name": "Zeal", "elite": False},
    {"_id": 16, "name": "Honor", "elite": False},
    {"_id": 62, "name": "Firebrand", "elite": True},
]


def cache(**collections):
    return subject.gw2_db(**{"specializations": SPECIALIZATIONS, "titles": [], "items": [], **collections})


# --- /character info -------------------------------------------------------------------


async def test_info(gamedata):
    char = character(guild="GUILD-ID", title=7)
    responses = [(200, char), (200, {"id": "GUILD-ID", "name": "Example Guild", "tag": "EX"})]
    db = cache(titles=[{"_id": 7, "name": "Dragonslayer"}])
    embed, requests, _, _ = await subject.character_command("info", responses, db=db, character="example char")
    assert embed["description"] == "Dragonslayer"
    assert fields(embed) == [
        ("Created at", "2020-03-10"),
        ("Played for", "10 hours 0 minutes"),
        ("Guild", "[EX] Example Guild"),
        ("Deaths", "12"),
        ("Deaths per hour", "1.2"),
        ("Crafting", "Level 500 Armorsmith\nLevel 150 Chef"),
    ]
    assert embed["author"]["name"] == "example char"
    assert embed["footer"]["text"] == "A female human firebrand"
    assert embed["color"] == int(gamedata["professions"]["guardian"]["color"], 0)
    assert requests == [
        (API + "characters/Example%20Char", {"access_token": "KEY"}),
        (API + "guild/GUILD-ID", {}),
    ]


async def test_info_without_guild_title_or_crafting():
    char = character(crafting=[])
    embed, requests, _, _ = await subject.character_command("info", [(200, char)], db=cache(), character="Example Char")
    assert embed.get("description") is None
    assert [name for name, _ in fields(embed)] == ["Created at", "Played for", "Deaths", "Deaths per hour"]
    assert len(requests) == 1


async def test_info_for_someone_elses_public_character():
    public = [{"name": "Example Char", "owner": 2, "owner_acc_name": "Other.5678"}]
    responses = [(404, {"text": "no such character"}), (200, character())]
    embed, requests, _, _ = await subject.character_command(
        "info", responses, db=cache(), public=public, character="Example Char"
    )
    assert embed["footer"]["text"] == "A female human firebrand"
    assert [url for url, _ in requests] == [API + "characters/Example%20Char"] * 2


async def test_info_unknown_character():
    sent, _, _, _ = await subject.character_command(
        "info", [(404, {"text": "no such character"})], db=cache(), character="Nobody"
    )
    assert sent == "Invalid character name"


# --- /character list ------------------------------------------------------------------

LIST = [
    character("Charlie", age=7200, created="2021-01-01T00:00:00Z", profession="Warrior", build_tabs=[build_tab(elite=16)]),
    character("Alpha", age=36000, created="2022-01-01T00:00:00Z", level=20),
    character("Bravo", age=3600, created="2019-01-01T00:00:00Z", build_tabs=[build_tab(elite=16)]),
]


@pytest.mark.parametrize(
    "info, description, lines",
    [
        ("name", "Sorted by name",
         ["**(Firebrand)** **Alpha** (Level 20)", "**(Guardian)** **Bravo**", "**(Warrior)** **Charlie**"]),
        ("age", "Sorted by time played",
         ["**(Firebrand)** **Alpha**: 10h 0m", "**(Warrior)** **Charlie**: 2h 0m", "**(Guardian)** **Bravo**: 1h 0m"]),
        ("profession", "Sorted by profession",
         ["**(Firebrand)** **Alpha** (Level 20)", "**(Guardian)** **Bravo**", "**(Warrior)** **Charlie**"]),
    ],
)
async def test_list(info, description, lines):
    embed, requests, _, _ = await subject.character_command("list", [(200, LIST)], db=cache(), info=info)
    assert embed["title"] == "Your characters"
    assert embed["description"] == description
    assert fields(embed) == [("List", "\n".join(lines))]
    assert requests == [(API + "characters?page=0&page_size=200", {"access_token": "KEY"})]


async def test_list_needs_builds_permission():
    from gw2bot.gw2api.errors import APIKeyError

    with pytest.raises(APIKeyError, match="`builds`"):
        await subject.character_command("list", [], permissions=("account", "characters"))


# --- /character birthdays --------------------------------------------------------------


async def test_birthdays():
    characters = [
        character("Alpha", created="2020-03-10T00:00:00Z"),
        character("Bravo", created="2020-03-20T00:00:00Z", build_tabs=[build_tab(elite=16)]),
        character("Charlie", created="2023-04-01T00:00:00Z", build_tabs=[build_tab(elite=16)]),
    ]
    embed, _, _, _ = await subject.character_command(
        "birthdays", [(200, characters)], db=cache(), now=datetime.datetime(2024, 3, 6, 12, tzinfo=UTC)
    )
    assert embed["title"] == "Days until..."
    # Years of 365 days: the 2020 characters' 4th birthdays are a day
    # early after the leap day
    assert fields(embed) == [
        ("4th Birthday", " Alpha: **3**\n Bravo: **13**"),
        ("1st Birthday", " Charlie: **25**"),
    ]


# --- /character crafting ------------------------------------------------------------------


async def test_crafting():
    characters = [character("Alpha"), character("Bravo", crafting=[])]
    embed, requests, _, _ = await subject.character_command("crafting", [(200, characters)])
    assert embed["description"] == "Crafting overview"
    assert fields(embed) == [("Alpha", "Level 500 Armorsmith\nLevel 150 Chef")]
    assert requests == [(API + "characters?page=0&page_size=200", {"access_token": "KEY"})]


# --- /character togglepublic --------------------------------------------------------------

TOGGLED = ("Character status successfully changed. Anyone can check public characters gear and build - "
           "the rest is still private. To make character private again, type the same command.")


async def test_make_public_then_private():
    sent, _, dms, docs = await subject.character_command(
        "togglepublic", [(200, ["Alpha", "Bravo"])], character_or_all="alpha"
    )
    assert sent == TOGGLED
    assert dms == []
    assert [{k: v for k, v in d.items() if k != "_id"} for d in docs] == [
        {"name": "Alpha", "owner": 1, "owner_acc_name": "Example.1234"},
    ]
    _, _, _, docs = await subject.character_command(
        "togglepublic", [(200, ["Alpha", "Bravo"])], public=docs, character_or_all="Alpha"
    )
    assert docs == []


async def test_toggle_all():
    public = [{"name": "Bravo", "owner": 1, "owner_acc_name": "Example.1234"}]
    sent, _, dms, docs = await subject.character_command(
        "togglepublic", [(200, ["Alpha", "Bravo"])], public=public, character_or_all="all"
    )
    assert sent == TOGGLED
    assert dms == ["Alpha is now public\nBravo is now private"]
    assert [d["name"] for d in docs] == ["Alpha"]


async def test_toggle_unknown_character():
    sent, _, _, docs = await subject.character_command(
        "togglepublic", [(200, ["Alpha"])], character_or_all="Nobody"
    )
    assert sent == "Invalid character name"
    assert docs == []


# --- /character fashion ---------------------------------------------------------------------


async def test_fashion():
    equipment = [
        {"id": 10, "slot": "Helm", "location": "Equipped", "skin": 20, "dyes": [1, None, 2, 3]},
        {"id": 11, "slot": "Coat", "location": "EquippedFromLegendaryArmory", "dyes": []},
        {"id": 12, "slot": "Ring1", "location": "Equipped"},
        {"id": 13, "slot": "Boots", "location": "Armory", "dyes": [1]},
    ]
    db = cache(
        skins=[{"_id": 20, "name": "Fancy Hat"}],
        items=[{"_id": 11, "name": "Plain Coat"}],
        colors=[{"_id": 1, "name": "Abyss"}, {"_id": 2, "name": "Celestial"}],
    )
    embed, _, _, _ = await subject.character_command(
        "fashion", [(200, character(equipment=equipment))], db=db, character="Example Char"
    )
    assert embed["description"] == "Fashion"
    # Uncached dyes are left out
    assert fields(embed) == [("Fancy Hat", "Channel 1: Abyss\nChannel 3: Celestial"), ("Plain Coat", ZWSP)]
    assert embed["author"]["name"] == "Example Char"
    assert embed["footer"]["text"] == "A level 80 firebrand "


async def test_fashion_unknown_character():
    sent, _, _, _ = await subject.character_command(
        "fashion", [(404, {"text": "no such character"})], db=cache(), character="Nobody"
    )
    assert sent == "Invalid character name"


# --- /sab ------------------------------------------------------------------------------------


async def test_sab_unlocks(gamedata):
    unlocked = [{"name": name} for name in gamedata["sab"]["unlocks"][2:]]
    sent, requests, _, _ = await subject.character_command(
        "sab unlocks", [(200, {"unlocks": unlocked, "zones": []})], permissions=("account", "characters", "progression"),
        character="example char",
    )
    assert sent == "This character is missing the following SAB upgrades:\n```fix\nChain Stick\nSlingshot\n```"
    assert requests == [(API + "characters/Example%20Char/sab", {"access_token": "KEY"})]


async def test_sab_all_unlocked(gamedata):
    unlocked = [{"name": name} for name in gamedata["sab"]["unlocks"]]
    sent, _, _, _ = await subject.character_command(
        "sab unlocks", [(200, {"unlocks": unlocked, "zones": []})], permissions=("account", "characters", "progression"),
        character="Example Char",
    )
    assert sent == "You have unlocked all the upgrades on this character! Congratulations!"


async def test_sab_zones():
    zones = [{"id": i, "world": world, "zone": zone, "mode": mode}
             for i, (world, zone, mode) in enumerate(
                 (w, z, m) for w in (1, 2) for m in ("infantile", "normal", "tribulation") for z in (1, 2, 3))
             if (world, zone, mode) not in {(2, 3, "tribulation"), (1, 1, "normal")}]
    sent, _, _, _ = await subject.character_command(
        "sab zones", [(200, {"unlocks": [], "zones": zones})], permissions=("account", "characters", "progression"),
        character="Example Char",
    )
    assert sent == ("This character is missing the following SAB zones:\n"
                    "```fix\nW1Z1 Normal mode\nW2Z3 Tribulation mode\n```")


async def test_sab_unknown_character():
    sent, _, _, _ = await subject.character_command(
        "sab zones", [(404, {"text": "no such character"})], permissions=("account", "characters", "progression"),
        character="Nobody",
    )
    assert sent == "Invalid character name"


# --- Character autocomplete ----------------------------------------------------------------

NOW = datetime.datetime(2024, 3, 6, 12)


def with_cache(characters, updated):
    return {**subject.stored_key(["account", "characters"]),
            "character_cache": {"Example_1234": {"last_update": updated, "characters": characters}}}


async def test_autocomplete_from_the_cache():
    stored = with_cache(["Alpha", "Bravo", "Alphonse"], NOW - datetime.timedelta(days=1))
    choices, writes, requests = await subject.character_choices("alph", stored, now=NOW)
    assert choices == ["Alpha", "Alphonse"]
    assert writes == requests == []


async def test_autocomplete_fills_the_cache():
    choices, writes, requests = await subject.character_choices(
        "", subject.stored_key(["account", "characters"]), [(200, ["Alpha", "Bravo"])], now=NOW
    )
    assert choices == ["Alpha", "Bravo"]
    assert writes == [("set", {"character_cache.Example_1234": {"last_update": NOW, "characters": ["Alpha", "Bravo"]}})]
    assert requests == [(API + "characters", {"access_token": "KEY"})]


async def test_autocomplete_refreshes_an_old_cache_in_the_background():
    stored = with_cache(["Alpha"], NOW - datetime.timedelta(days=4))
    choices, writes, _ = await subject.character_choices("", stored, [(200, ["Alpha", "Bravo"])], now=NOW)
    assert choices == ["Alpha"]
    assert writes == [("set", {"character_cache.Example_1234": {"last_update": NOW, "characters": ["Alpha", "Bravo"]}})]


async def test_autocomplete_without_a_key():
    choices, writes, requests = await subject.character_choices("a", {}, now=NOW)
    assert choices == writes == requests == []


# --- Fixes ------------------------------------------------------------------------------------


async def test_info_shows_the_elite_specialization():
    embed, _, _, _ = await subject.character_command("info", [(200, character())], db=cache(), character="Example Char")
    assert embed["footer"]["text"] == "A female human firebrand"
    assert embed["thumbnail"]["url"] == subject.profession_icon("Firebrand")


@pytest.fixture
def helsinki_time(monkeypatch):
    """Run in a timezone other than UTC."""
    monkeypatch.setenv("TZ", "Europe/Helsinki")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


async def test_list_by_creation_date(helsinki_time):
    embed, _, _, _ = await subject.character_command("list", [(200, LIST)], db=cache(), info="created")
    assert embed["description"] == "Sorted by date of creation"
    assert fields(embed) == [("List", "\n".join([
        "**(Guardian)** **Bravo**: <t:1546300800:f>",  # 2019-01-01 UTC
        "**(Warrior)** **Charlie**: <t:1609459200:f>",
        "**(Firebrand)** **Alpha**: <t:1640995200:f>",
    ]))]


async def test_info_for_a_new_character():
    embed, _, _, _ = await subject.character_command(
        "info", [(200, character(age=0, deaths=0))], db=cache(), character="Example Char"
    )
    assert dict(fields(embed))["Deaths per hour"] == "0.0"


async def test_fashion_with_uncached_item():
    equipment = [{"id": 10, "slot": "Helm", "location": "Equipped", "dyes": []}]
    embed, _, _, _ = await subject.character_command(
        "fashion", [(200, character(equipment=equipment))], db=cache(colors=[], skins=[]), character="Example Char"
    )
    assert fields(embed) == [("Unknown item", ZWSP)]


# --- /character gear --------------------------------------------------------------------------


def gear_cache(**changes):
    collections = {
        "professions": [{"_id": "Guardian", "code": 1, "skills_by_palette": []}],
        "specializations": [],
        "skills": [],
        "legends": [],
        "items": [
            {"_id": 101, "name": "Helm", "rarity": "Ascended", "details": {"type": "Helm", "defense": 97}},
            {"_id": 200, "name": "Ring", "rarity": "Ascended",
             "details": {"type": "Ring", "infix_upgrade": {"id": 1, "attributes": [
                 {"attribute": "Power", "modifier": 126}]}}},
            {"_id": 300, "name": "Greatsword", "rarity": "Exotic", "details": {"type": "Greatsword"}},
            {"_id": 500, "name": "Superior Rune of Strength", "rarity": "Exotic",
             "details": {"type": "Rune", "bonuses": ["+25 Power"]}},
            {"_id": 600, "name": "Superior Sigil of Force", "rarity": "Exotic",
             "details": {"type": "Sigil", "infix_upgrade": {"id": 2, "attributes": [],
                                                            "buff": {"description": "+5% Damage"}}}},
        ],
        "itemstats": [{"_id": 161, "name": "Berserker's"}, {"_id": 1, "name": "Assassin's"}],
    }
    return subject.gw2_db(**{**collections, **changes})


def geared(**changes):
    berserker = {"id": 161, "attributes": {"Power": 63, "Precision": 45, "CritDamage": 45}}
    return character(
        equipment=[
            {"id": 101, "slot": "Helm", "location": "Equipped", "tabs": [1], "upgrades": [500], "stats": berserker},
            {"id": 200, "slot": "Ring1", "location": "Equipped", "tabs": [1]},
            {"id": 300, "slot": "WeaponA1", "location": "Equipped", "tabs": [1], "upgrades": [600]},
        ],
        equipment_tabs=[{"tab": 1, "name": "Power", "is_active": True, "equipment": [
            {"id": 101, "slot": "Helm", "upgrades": [500], "stats": berserker},
            {"id": 200, "slot": "Ring1"},
            {"id": 300, "slot": "WeaponA1", "upgrades": [600]},
        ]}],
        build_tabs=[build_tab(elite=99)],
        **changes,
    )


def image_channel():
    from unittest.mock import AsyncMock, MagicMock

    channel = MagicMock()
    channel.send = AsyncMock(return_value=MagicMock(attachments=[]))
    return channel


async def test_gear(gamedata):
    embed, requests, _, _ = await subject.character_command(
        "gear", [(200, geared())], db=gear_cache(), config={"image_channel": 5}, channel=image_channel(),
        character="Example Char",
    )
    assert embed["author"]["name"] == "Example Char"
    assert embed["footer"]["text"] == "A level 80 guardian "
    assert embed["description"] == "Build template:\n>  *PvE*\nEquipment template:\n>  *Power*"
    assert fields(embed) == [
        ("> **ARMOR**", "Berserker's\nNONE\nNONE\nNONE\nNONE\nNONE\n*Superior Rune of Strength* (1/6)"),
        ("> **WEAPON SET #1**", " Greatsword\n*Superior Sigil of Force*"),
        ("> **TRINKETS**", "Assassin's\nNONE\nNONE\nNONE\nNONE\nNONE"),
        ("> **BONUSES FROM UPGRADES**", "None found"),
        ("> **ATTRIBUTES**", "\n".join([
            "**Power**: 1214", "**Toughness**: 1000", "**Vitality**: 1000", "**Precision**: 1045",
            "**Ferocity**: 45", "**Condition Damage**: 0", "**Expertise**: 0", "**Concentration**: 0",
            "**Agony Resistance**: 0",
        ])),
        (ZWSP, "\n".join([
            ZWSP, ZWSP, "**Armor**: 1097", "**Health**: 11645", "**Critical Chance**: 7.14%",
            "**Critical Damage**: 153%", "**Healing Power**: 0", "**Condition Duration**: 0%",
            "**Boon Duration**: 0%",
        ])),
        ("Build code", "[&DQEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=]"),
    ]
    assert requests == [(API + "characters/Example%20Char", {"access_token": "KEY"})]


async def test_gear_needs_an_image_channel():
    sent, requests, _, _ = await subject.character_command(
        "gear", [], db=gear_cache(), config={"cache": {}}, character="Example Char"
    )
    assert sent == "The owner must set the image channel using $imagechannel command."
    assert requests == []


async def test_gear_unknown_character():
    sent, _, _, _ = await subject.character_command(
        "gear", [(404, {"text": "no such character"})], db=gear_cache(), config={"image_channel": 5},
        channel=image_channel(), character="Nobody",
    )
    assert sent == "Invalid character name"


async def test_gear_with_uncached_stats():
    embed, _, _, _ = await subject.character_command(
        "gear", [(200, geared())], db=gear_cache(itemstats=[]), config={"image_channel": 5},
        channel=image_channel(), character="Example Char",
    )
    # Just the rarity emoji, which the tests don't have
    assert fields(embed)[0][1] == "NONE\nNONE\nNONE\nNONE\nNONE\nNONE\n*Superior Rune of Strength* (1/6)"


async def test_gear_with_uncached_equipment():
    items = [doc for doc in gear_cache().items.docs if doc["_id"] != 300]
    embed, _, _, _ = await subject.character_command(
        "gear", [(200, geared())], db=gear_cache(items=items), config={"image_channel": 5},
        channel=image_channel(), character="Example Char",
    )
    assert fields(embed)[1] == ("> **WEAPON SET #1**", "Unknown item")
