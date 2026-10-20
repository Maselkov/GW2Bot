import base64
import datetime
import struct

import pytest

import subject

UTC = datetime.timezone.utc
D = datetime.date


# --- Chat codes ------------------------------------------------------------
# Format: https://wiki.guildwars2.com/wiki/Chat_link_format


def decode_item_code(code):
    """Parse an item chat code per the wiki spec, ignoring trailing bytes."""
    raw = base64.b64decode(code[2:-1])
    assert raw[0] == 0x02
    count = raw[1]
    item_id = int.from_bytes(raw[2:5], "little")
    flags = raw[5]
    pos = 6
    extras = {}
    for name, bit in (("skin", 0x80), ("upgrade1", 0x40), ("upgrade2", 0x20)):
        if flags & bit:
            extras[name] = struct.unpack_from("<I", raw, pos)[0]
            pos += 4
    return count, item_id, extras


@pytest.mark.parametrize(
    "args, expected",
    [
        ((46762, 1, None, []), (1, 46762, {})),
        ((46762, 250, None, []), (250, 46762, {})),
        ((46762, 1, 3709, []), (1, 46762, {"skin": 3709})),
        ((46762, 1, None, [24575]), (1, 46762, {"upgrade1": 24575})),
        ((46762, 1, 3709, [24575]), (1, 46762, {"skin": 3709, "upgrade1": 24575})),
        (
            (46762, 1, 3709, [24575, 24615]),
            (1, 46762, {"skin": 3709, "upgrade1": 24575, "upgrade2": 24615}),
        ),
    ],
)
def test_chat_code_roundtrip(args, expected):
    assert decode_item_code(subject.chat_code(*args)) == expected


@pytest.mark.parametrize(
    "args, code",
    [
        ((46762, 1, None, []), "[&AgGqtgAA]"),
        ((23029, 1, None, []), "[&AgH1WQAA]"),
        ((46762, 1, None, [24575]), "[&AgGqtgBA/18AAA==]"),
        ((46762, 1, 3709, []), "[&AgGqtgCAfQ4AAA==]"),
        ((46762, 1, 3709, [24575, 24615]), "[&AgGqtgDgfQ4AAP9fAAAnYAAA]"),
    ],
)
def test_chat_code_matches_wiki_examples(args, code):
    assert subject.chat_code(*args) == code


# --- Formatting ------------------------------------------------------------


@pytest.mark.parametrize(
    "copper, expected",
    [
        (1234567, "123 gold 45 silver 67 copper "),
        (10000, "1 gold "),
        (10001, "1 gold 1 copper "),
        (5, "5 copper "),
        (0, ""),
    ],
)
def test_format_coins(copper, expected):
    assert subject.format_coins(copper) == expected


@pytest.mark.parametrize(
    "seconds, short, expected",
    [
        (5 * 3600 + 7 * 60, False, "5 hours 7 minutes"),
        (5 * 3600 + 7 * 60, True, "5h 7m"),
        (5 * 3600 + 7 * 60 + 31, False, "5 hours 8 minutes"),
        (59, False, "1 minutes"),
        (0, True, "0m"),
    ],
)
def test_format_age(seconds, short, expected):
    assert subject.format_age(seconds, short=short) == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("CritDamage", "Critical Damage"),
        ("Healing", "Healing Power"),
        ("ConditionDamage", "Condition Damage"),
        ("BoonDuration", "Boon Duration"),
        ("defense", "Armor"),
        ("Power", "Power"),
    ],
)
def test_readable_attribute(name, expected):
    assert subject.readable_attribute(name) == expected


@pytest.mark.parametrize(
    "td, expected",
    [
        (datetime.timedelta(hours=2, minutes=5, seconds=59), "2 hours and 5 minutes"),
        (datetime.timedelta(minutes=5), "5 minutes"),
        (datetime.timedelta(seconds=30), "0 minutes"),
    ],
)
def test_format_timedelta(td, expected):
    assert subject.format_timedelta(td) == expected


def test_embed_list_lines_short_fits_one_field():
    assert subject.embed_list_lines(["a", "b"], "Name") == [("Name", "a\nb")]


def test_embed_list_lines_splits_at_1024():
    lines = ["x" * 300] * 10
    fields = subject.embed_list_lines(lines, "Name")
    assert fields[0][0] == "Name"
    assert all(name == "\u200b" for name, _ in fields[1:])
    assert all(len(value) <= 1024 for _, value in fields)
    assert sum(value.count("x" * 300) for _, value in fields) == 10


def test_embed_list_lines_respects_total_limit():
    fields = subject.embed_list_lines(["y" * 1000] * 30, "Name")
    assert sum(len(value) for _, value in fields) <= 6000
    assert len(fields) == 5


def test_cleanup_xml_tags():
    assert subject.cleanup_xml_tags("<c=@reminder>Hello</c> <br>world") == "Hello world"


def test_search_pattern_is_case_insensitive_prefix_and_escaped():
    pattern = subject.search_pattern("Zojja's (Claymore")
    assert pattern.match("zojja's (claymore of doom")
    assert not pattern.match("Claymore")


# --- Achievements ----------------------------------------------------------

ACHIEVEMENT = {
    "tiers": [{"count": 1, "points": 5}, {"count": 5, "points": 10}],
    "point_cap": 50,
}


@pytest.mark.parametrize(
    "progress, expected",
    [(None, 0), ({"current": 0}, 0), ({"current": 1}, 1), ({"current": 7}, 2)],
)
def test_tier_progress(progress, expected):
    assert subject.tier_progress(ACHIEVEMENT["tiers"], progress) == expected


def test_max_ap():
    assert subject.max_ap(ACHIEVEMENT) == 15
    assert subject.max_ap(ACHIEVEMENT, repeatable=True) == 50
    assert subject.max_ap(None) == 0


@pytest.mark.parametrize(
    "progress, expected",
    [
        (None, 0),
        ({"current": 1}, 5),
        ({"current": 5}, 15),
        ({"current": 5, "repeated": 2}, 45),
        ({"current": 5, "repeated": 10}, 50),  # capped at point_cap
    ],
)
def test_earned_ap(progress, expected):
    assert subject.earned_ap(ACHIEVEMENT, progress) == expected


# --- Skills ----------------------------------------------------------------


@pytest.mark.parametrize(
    "weapon, hits, multiplier, expected",
    [
        # damage = hits * round(base * 1000 * multiplier / 2597)
        ("Greatsword", 1, 1.0, "403 (1.0)"),
        ("Rifle", 1, 2.0, "844 (2.0)"),
        ("Dagger", 3, 0.5, "549 (1.5)"),
        (None, 1, 1.0, "266 (1.0)"),  # no weapon: 690.5 base
    ],
)
def test_skill_damage(weapon, hits, multiplier, expected):
    skill = {
        "facts": [
            {"type": "Damage", "text": "Damage", "hit_count": hits, "dmg_multiplier": multiplier}
        ]
    }
    if weapon:
        skill["weapon_type"] = weapon
    [(field, value)] = subject.skill_fields(skill)
    assert value == expected
    assert field == ("Damage ({}x)".format(hits) if hits > 1 else "Damage")


def test_skill_fields_order_and_format():
    skill = {
        "facts": [
            {"type": "StunBreak"},
            {"type": "Radius", "text": "Radius", "distance": 1200},
            {"type": "Recharge", "text": "Recharge", "value": 25},
            {"type": "Buff", "status": "Might", "apply_count": 3, "duration": 10, "description": "+Power"},
            {"type": "ComboFinisher", "text": "Combo Finisher", "finisher_type": "Blast", "percent": 20},
            {"type": "Unblockable"},
        ]
    }
    assert subject.skill_fields(skill) == [
        ("Recharge", "25s"),
        ("3 Might(10s)", "+Power"),
        ("Radius", "1,200"),
        ("Unblockable", None),
        ("Combo Finisher", "Blast (20%)"),
        ("Breaks stun", None),
    ]


# --- Dailies ---------------------------------------------------------------


@pytest.mark.parametrize(
    "date, expected",
    [
        (D(2023, 1, 1), 0),
        (D(2023, 2, 28), 58),
        (D(2024, 2, 29), 59),
        # Non-leap years skip index 59 so a date maps to the same index every year
        (D(2023, 3, 1), 60),
        (D(2024, 3, 1), 60),
        (D(2023, 12, 31), 365),
        (D(2024, 12, 31), 365),
    ],
)
def test_year_day(date, expected):
    assert subject.year_day(date) == expected


DAILY_NAMES = {
    2238: "Daily Recommended Fractal—Scale 15",
    2896: "Daily Tier 1 Urban Battleground",
    2903: "Daily Tier 4 Molten Furnace",
    2941: "Daily Tier 4 Urban Battleground",
    3038: "Daily Tier 4 Chaos",
    3184: "Daily Recommended Fractal—Scale 66",
    3346: "Daily Lake Doric Bosses",
    4367: "Daily Jahai Bluffs Rift Event",
    9126: "Raid Bounty: Vale Guardian",
    9168: "Raid Bounty: Harvest Temple",
}
# Shaped like /v2/achievements/categories with schema 2022-03-23
DAILY_ACHIEVEMENT_CATEGORIES = [
    {
        "id": 88,
        "achievements": [{"id": 2941}, {"id": 2238}, {"id": 2896}, {"id": 3038}],
        "tomorrow": [{"id": 3184}, {"id": 2903}],
    },
    {"id": 475, "achievements": [{"id": 9168}], "tomorrow": [{"id": 9126}]},
    {"id": 238, "achievements": [{"id": 3346}], "tomorrow": []},
    # No tomorrow list, and an achievement whose name couldn't be fetched
    {"id": 243, "achievements": [{"id": 4367}, {"id": 99999}]},
]
ALL_DAILY_CATEGORIES = ["psna", "fractals", "raids", "lw"]


def test_daily_rotation():
    rotation = subject.daily_rotation(DAILY_ACHIEVEMENT_CATEGORIES, DAILY_NAMES)
    assert rotation["today"] == {
        # Only tier 4 and the recommended fractals
        "fractals": [
            "Daily Recommended Fractal—Scale 15",
            "Daily Tier 4 Chaos",
            "Daily Tier 4 Urban Battleground",
        ],
        "raids": ["Raid Bounty: Harvest Temple"],
        "lws3": ["Daily Lake Doric Bosses"],
        "lws4": ["Daily Jahai Bluffs Rift Event"],
    }
    assert rotation["tomorrow"] == {
        "fractals": ["Daily Recommended Fractal—Scale 66", "Daily Tier 4 Molten Furnace"],
        "raids": ["Raid Bounty: Vale Guardian"],
        "lws3": [],
        "lws4": [],
    }


def test_daily_rotation_without_categories():
    rotation = subject.daily_rotation([], DAILY_NAMES)
    assert rotation["today"] == {"fractals": [], "raids": [], "lws3": [], "lws4": []}


@pytest.mark.parametrize(
    "saved, expected",
    [
        (None, ALL_DAILY_CATEGORIES),
        (["fractals", "psna"], ["psna", "fractals"]),
        # The notifier's default before the Wizard's Vault
        (["psna", "psna_later", "pve", "pvp", "wvw", "fractals", "strikes"], ALL_DAILY_CATEGORIES),
        (["strikes"], ["raids"]),
        (["pvp", "wvw"], ALL_DAILY_CATEGORIES),
    ],
)
def test_daily_categories(saved, expected):
    assert subject.daily_categories(saved) == expected


def _today_rotation():
    return subject.daily_rotation(DAILY_ACHIEVEMENT_CATEGORIES, DAILY_NAMES)["today"]


def test_daily_embed_raids_and_living_world():
    fields = subject.daily_fields(["lw", "raids"], _today_rotation(), D(2024, 3, 1))
    assert fields == [
        ("RAID BOUNTIES", "Harvest Temple"),
        ("LIVING WORLD SEASON 3", "Lake Doric Bosses"),
        ("LIVING WORLD SEASON 4", "Jahai Bluffs Rift Event"),
    ]


def test_daily_embed_fractals():
    fields = dict(subject.daily_fields(["fractals"], _today_rotation(), D(2024, 3, 1)))
    assert list(fields) == ["> Daily Fractals", "> CM Instabilities", "> Recommended Fractals"]
    assert fields["> Daily Fractals"].startswith("Chaos\n")
    assert fields["> Recommended Fractals"] == "15 Thaumanova Reactor"


def test_daily_embed_psna(gamedata):
    # Monday 06:00 UTC: Sunday's agents until the 08:00 reset
    now = datetime.datetime(2024, 3, 4, 6, tzinfo=UTC)
    reset = int(datetime.datetime(2024, 3, 4, 8, tzinfo=UTC).timestamp())
    assert subject.daily_fields(["psna"], _today_rotation(), now) == [
        ("PSNA", gamedata["pact_supply"][6]),
        (f"PSNA <t:{reset}:R>", gamedata["pact_supply"][0]),
    ]


def test_daily_embed_psna_tomorrow(gamedata):
    # The notifier posts Monday's dailies on Sunday evening
    now = datetime.datetime(2024, 3, 3, 23, 40, tzinfo=UTC)
    reset = int(datetime.datetime(2024, 3, 4, 8, tzinfo=UTC).timestamp())
    assert subject.daily_fields(["psna"], _today_rotation(), now, tomorrow=True) == [
        ("PSNA", gamedata["pact_supply"][6]),
        (f"PSNA <t:{reset}:R>", gamedata["pact_supply"][0]),
    ]


def test_daily_embed_rejects_the_old_cache():
    old_cache = {"pve": ["Daily Mystic Forger"], "fractals": [], "psna": ["..."]}
    with pytest.raises(ValueError):
        subject.daily_fields(["psna"], old_cache, D(2024, 3, 1))


def test_pact_supply_agents_follow_weekday(gamedata):
    # Resets at 08:00 UTC; noon UTC on Monday 2024-03-04 is already Monday's list
    assert subject.pact_supply_agents(D(2024, 3, 4)) == gamedata["pact_supply"][0]
    assert subject.pact_supply_agents(D(2024, 3, 10)) == gamedata["pact_supply"][6]


def test_pact_supply_agents_reset_at_0800_utc(gamedata):
    monday = datetime.datetime(2024, 3, 4, 7, 59, tzinfo=UTC)
    assert subject.pact_supply_agents(monday) == gamedata["pact_supply"][6]


def test_instabilities():
    assert subject.instabilities(98, D(2024, 3, 1)) == ["Outflanked", "Afflicted", "Boon Overload"]
    assert subject.instabilities(50, D(2024, 3, 1)) is None


def test_cm_instabilities():
    assert subject.cm_instabilities(D(2024, 3, 1)) == {
        "Nightmare": ["Boon Overload", "Afflicted", "Stick Together"],
        "Shattered Observatory": ["No Pain, No Gain", "Fractal Vindicators", "Hamstrung"],
        "Sunqua Peak": ["Outflanked", "Afflicted", "Boon Overload"],
        "Silent Surf": ["Hamstrung", "Frailty", "Afflicted"],
        "Lonely Tower": ["Vengeance", "Fractal Vindicators", "Flux Bomb"],
    }


# --- Event timers ----------------------------------------------------------

LATE = datetime.datetime(2024, 3, 1, 23, 50, tzinfo=UTC)


def test_upcoming_bosses_cross_midnight():
    bosses = subject.upcoming_bosses(LATE, limit=4)
    assert bosses == [
        ("Admiral Taidha Covington", datetime.datetime(2024, 3, 2, 0, 0, tzinfo=UTC)),
        ("Tequatl the Sunless", datetime.datetime(2024, 3, 2, 0, 0, tzinfo=UTC)),
        ("Svanir Shaman Chief", datetime.datetime(2024, 3, 2, 0, 15, tzinfo=UTC)),
        ("Ley-Line Anomaly", datetime.datetime(2024, 3, 2, 0, 20, tzinfo=UTC)),
    ]


def test_upcoming_bosses_are_future_and_sorted():
    now = datetime.datetime(2024, 3, 1, 13, 7, tzinfo=UTC)
    times = [t for _, t in subject.upcoming_bosses(now, limit=20)]
    assert len(times) == 20
    assert all(t > now for t in times)
    assert times == sorted(times)


def test_seconds_until_boss():
    assert subject.seconds_until_boss("Tequatl the Sunless", LATE) == 600
    assert subject.seconds_until_boss("Karka Queen", LATE) == (2 * 60 + 10) * 60


@pytest.mark.parametrize(
    "now, phase, expected",
    [
        (datetime.datetime(2024, 3, 1, 0, 0, tzinfo=UTC), "Dawn", 25 * 60),
        (datetime.datetime(2024, 3, 1, 1, 59, tzinfo=UTC), "Dawn", 26 * 60),
        # Already night: the reminder targets the next night, at 01:45
        (datetime.datetime(2024, 3, 1, 0, 0, tzinfo=UTC), "Night", 105 * 60),
    ],
)
def test_seconds_until_phase(now, phase, expected):
    assert subject.seconds_until_phase("day", "Tyrian cycle", phase, now) == expected


def test_timer_state_merges_wrapped_phase():
    # Tyrian night spans the end of one 2h window and the start of the next
    now = datetime.datetime(2024, 3, 1, 1, 58, tzinfo=UTC)
    state = subject.timer_state("day", now)
    assert state["Tyrian cycle"] == (
        "Night",
        "Dawn",
        datetime.datetime(2024, 3, 1, 2, 25, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "group",
    [
        "hot",
        "pof",
        "ibs",
        "eod",
        "soto",
        "day",
    ],
)
def test_timer_next_phase_is_always_in_future(group):
    start = datetime.datetime(2024, 3, 1, 0, 0, tzinfo=UTC)
    for minute in range(120):
        now = start + datetime.timedelta(minutes=minute)
        for map_name, (_, _, next_at) in subject.timer_state(group, now).items():
            assert next_at > now, (map_name, now.time())


# --- Error messages --------------------------------------------------------


def test_api_inactive_error_message():
    from gw2bot.gw2api.errors import APIInactiveError

    assert subject.api_error_message(APIInactiveError()) == (
        "The API is currently down. Try again later."
    )


def test_api_error_messages():
    from gw2bot.gw2api.errors import APIError, APIInvalidKey, APIKeyError

    assert subject.api_error_message(APIKeyError("No key")) == "No key"
    assert "invalid" in subject.api_error_message(APIInvalidKey())
    assert subject.api_error_message(APIError("boom")) == (
        "API has responded with the following error: `boom`"
    )


def test_canthan_cycle():
    # Night 55 / Dawn 5 / Day 55 / Dusk 5 per the wiki; night spans the
    # end and start of each 2 hour window
    state = subject.timer_state("day", datetime.datetime(2024, 3, 1, 1, 58, tzinfo=UTC))
    assert state["Canthan cycle"] == (
        "Canthan Night",
        "Canthan Dawn",
        datetime.datetime(2024, 3, 1, 2, 35, tzinfo=UTC),
    )
    state = subject.timer_state("day", datetime.datetime(2024, 3, 1, 1, 36, tzinfo=UTC))
    assert state["Canthan cycle"] == (
        "Canthan Dusk",
        "Canthan Night",
        datetime.datetime(2024, 3, 1, 1, 40, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "team, expected",
    [("11001", 11001), ("Moogooloo", 11001), (" kormir's library ", 12013), ("Anvil Rock", None)],
)
def test_find_wvw_team(team, expected):
    assert subject.find_wvw_team(team) == expected


def test_wvw_team_autocomplete():
    assert subject.wvw_team_choices("moo") == [("Moogooloo (NA)", "11001")]
    assert subject.wvw_team_choices("aviary") == [("Great House Aviary (EU)", "12014")]
    assert len(subject.wvw_team_choices("")) == 25


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Guardian", "https://wiki.guildwars2.com/images/6/6c/Guardian_tango_icon_200px.png"),
        ("guardian", "https://wiki.guildwars2.com/images/6/6c/Guardian_tango_icon_200px.png"),
        ("Dragonhunter", "https://wiki.guildwars2.com/images/1/1f/Dragonhunter_tango_icon_200px.png"),
    ],
)
def test_profession_icon(name, expected):
    assert subject.profession_icon(name) == expected
