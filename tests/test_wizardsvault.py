import datetime

import pytest

from gw2bot.cogs.guildwars2.wizardsvault import (
    next_daily_reset,
    next_weekly_reset,
    objective_line,
    section_name,
)

UTC = datetime.timezone.utc


def objective(current, complete, claimed=False, track="PvE", acclaim=50):
    # Shaped like an entry of /v2/account/wizardsvault/{daily,weekly,special}
    return {
        "id": 57,
        "title": "Complete 10 Events",
        "track": track,
        "acclaim": acclaim,
        "progress_current": current,
        "progress_complete": complete,
        "claimed": claimed,
    }


@pytest.mark.parametrize(
    "obj, expected",
    [
        (objective(3, 10), "▫️ Complete 10 Events · 3/10 · 50 AA"),
        (objective(10, 10), "🎁 Complete 10 Events · ready to claim · 50 AA"),
        (objective(10, 10, claimed=True), "✅ Complete 10 Events · 50 AA"),
        # Single-step objectives don't show 0/1
        (objective(0, 1, acclaim=10), "▫️ Complete 10 Events · 10 AA"),
        # Collections report 0 steps until started
        (objective(0, 0, acclaim=150), "▫️ Complete 10 Events · 150 AA"),
        (objective(0, 1, track="WvW"), "▫️ [WvW] Complete 10 Events · 50 AA"),
    ],
)
def test_objective_line(obj, expected):
    assert objective_line(obj) == expected


def test_section_name():
    data = {
        "meta_progress_current": 1,
        "meta_progress_complete": 4,
        "meta_reward_astral": 20,
        "meta_reward_claimed": False,
    }
    assert section_name("Daily", data) == "Daily · 1/4 · reward: 20 AA"
    data["meta_reward_claimed"] = True
    assert section_name("Daily", data) == "Daily · 1/4 · reward claimed"


def test_next_daily_reset():
    now = datetime.datetime(2026, 10, 17, 20, 17, tzinfo=UTC)
    assert next_daily_reset(now) == datetime.datetime(2026, 10, 18, tzinfo=UTC)


@pytest.mark.parametrize(
    "now, expected",
    [
        # Saturday: the coming Monday
        (datetime.datetime(2026, 10, 17, 20, 17), datetime.datetime(2026, 10, 19, 7, 30)),
        # Monday before and after the reset
        (datetime.datetime(2026, 10, 19, 7, 29), datetime.datetime(2026, 10, 19, 7, 30)),
        (datetime.datetime(2026, 10, 19, 7, 30), datetime.datetime(2026, 10, 26, 7, 30)),
    ],
)
def test_next_weekly_reset(now, expected):
    assert next_weekly_reset(now.replace(tzinfo=UTC)) == expected.replace(tzinfo=UTC)
