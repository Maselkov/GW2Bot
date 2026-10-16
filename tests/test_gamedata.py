"""Consistency checks on the bundled game data files."""
import pytest

import subject

CM_FRACTALS = ["Nightmare", "Shattered Observatory", "Sunqua Peak", "Silent Surf", "Lonely Tower"]


def test_every_instability_scale_covers_a_leap_year(instabilities):
    for scale, days in instabilities["instabilities"].items():
        assert len(days) == 366, scale


def test_instability_ids_have_names(instabilities):
    names = instabilities["instability_names"]
    for scale, days in instabilities["instabilities"].items():
        for ids in days:
            for instability in ids:
                assert 0 <= instability < len(names), scale


def test_cm_fractals_have_instabilities(gamedata, instabilities):
    for fractal in CM_FRACTALS:
        top_scale = str(gamedata["fractals"][fractal][-1])
        assert top_scale in instabilities["instabilities"], fractal


def test_fractal_scales_are_unique(gamedata):
    scales = [s for levels in gamedata["fractals"].values() for s in levels]
    assert len(scales) == len(set(scales))


def test_pact_supply_has_a_list_per_weekday(gamedata):
    assert len(gamedata["pact_supply"]) == 7


def test_strike_rotations_are_not_empty(gamedata):
    assert gamedata["strike_missions"]
    assert gamedata["eod_strike_missions"]


def _timer_maps(gamedata):
    for group, maps in gamedata["event_timers"].items():
        if group == "bosses":
            continue
        for location in maps:
            yield group, location


@pytest.mark.parametrize(
    "group_map",
    [
        pytest.param(
            (group, location["name"]),
            marks=pytest.mark.xfail(
                strict=True,
                reason="Canthan cycle is Night 55 / Dawn 5 / Day 55 / Dusk 5 per the "
                "wiki; the data has a 20 min Dusk and no 5 min Dusk (115 min total)",
            )
            if location["name"] == "Canthan cycle"
            else (),
            id=f"{group}-{location['name']}",
        )
        for group, location in _timer_maps(subject._GAMEDATA)
    ],
)
def test_event_timer_maps_span_two_hours(gamedata, group_map):
    group, name = group_map
    [location] = [m for m in gamedata["event_timers"][group] if m["name"] == name]
    assert sum(phase["duration"] for phase in location["phases"]) == 120


@pytest.mark.parametrize(
    "group",
    [
        "hot",
        "pof",
        "ibs",
        "eod",
        pytest.param(
            "soto",
            marks=pytest.mark.xfail(
                strict=True, reason="timer_embed has no title for the soto group"
            ),
        ),
        "day",
    ],
)
def test_event_timer_groups_have_titles(group):
    assert subject.timer_titles()[group]


LEY_LINE_XFAIL = pytest.mark.xfail(
    strict=True,
    reason="Ley-Line Anomaly spawns every 2 hours (at :20) per the wiki; the "
    "data has a 5 hour interval",
)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(b["name"], marks=LEY_LINE_XFAIL if b["name"] == "Ley-Line Anomaly" else ())
        for b in subject._GAMEDATA["event_timers"]["bosses"]["normal"]
    ],
)
def test_normal_world_boss_times(gamedata, name):
    [boss] = [b for b in gamedata["event_timers"]["bosses"]["normal"] if b["name"] == name]
    hour, minute = boss["start_time"]
    assert 0 <= hour < 24 and 0 <= minute < 60
    assert 24 % boss["interval"] == 0


def test_hardcore_world_boss_times(gamedata):
    for boss in gamedata["event_timers"]["bosses"]["hardcore"]:
        for hour, minute in boss["times"]:
            assert 0 <= hour < 24 and 0 <= minute < 60, boss["name"]


@LEY_LINE_XFAIL
def test_ley_line_anomaly_schedule():
    import datetime

    start = datetime.datetime(2024, 3, 1, 0, 0, tzinfo=datetime.timezone.utc)
    times = [
        t.time()
        for name, t in subject.upcoming_bosses(start, limit=200)
        if name == "Ley-Line Anomaly" and t.date() == start.date()
    ]
    assert times == [datetime.time(h, 20) for h in range(0, 24, 2)]
