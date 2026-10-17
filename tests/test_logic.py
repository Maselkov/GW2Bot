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
    assert all(name == "​" for name, _ in fields[1:])
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


def test_living_world_dailies():
    assert subject.living_world_dailies(D(2024, 3, 1)) == [
        "Daily Living World Season 3 - Bloodstone Fen",
        "Daily Living World Season 4 - Domain of Istan",
    ]


def test_living_world_dailies_rotate_daily():
    seen = {tuple(subject.living_world_dailies(D(2024, 3, day))) for day in range(1, 7)}
    assert len(seen) == 6


def test_strikes():
    assert subject.strikes(D(2024, 3, 1)) == ["Cold War", "Aetherblade Hideout"]


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
    from gw2bot.cogs.guildwars2.exceptions import APIInactiveError

    assert subject.api_error_message(APIInactiveError()) == (
        "The API is currently down. Try again later."
    )


def test_api_error_messages():
    from gw2bot.cogs.guildwars2.exceptions import APIError, APIInvalidKey, APIKeyError

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
