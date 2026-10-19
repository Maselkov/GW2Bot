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


# --- /wizardsvault --------------------------------------------------------------

import subject  # noqa: E402

API = "https://api.guildwars2.com/v2/"
# Wednesday 2026-10-21 12:00 UTC: daily reset at midnight, weekly on Monday 07:30
NOW = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.timezone.utc)


def objective(title, current, complete, *, track="PvE", claimed=False, acclaim=10):
    return {"id": 1, "title": title, "track": track, "acclaim": acclaim,
            "progress_current": current, "progress_complete": complete, "claimed": claimed}


def period(objectives, current, complete, *, claimed=False, reward=20):
    return {"meta_progress_current": current, "meta_progress_complete": complete,
            "meta_reward_item_id": 1, "meta_reward_astral": reward,
            "meta_reward_claimed": claimed, "objectives": objectives}


DAILY = period([objective("Kill 10 enemies", 10, 10, claimed=True),
                objective("Complete a dungeon", 0, 1)], 1, 4)
WEEKLY = period([objective("Win 5 matches", 3, 5, track="PvP", acclaim=50)], 2, 14, claimed=True, reward=450)
SPECIAL = {"objectives": [objective("Defeat a world boss", 1, 1, acclaim=30)]}


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


async def test_wizards_vault():
    embed, requests = await subject.wizards_vault(DAILY, WEEKLY, SPECIAL, now=NOW)
    assert embed["title"] == "Wizard's Vault"
    daily_reset = int(datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc).timestamp())
    weekly_reset = int(datetime.datetime(2026, 10, 26, 7, 30, tzinfo=datetime.timezone.utc).timestamp())
    assert embed["description"] == f"Daily reset <t:{daily_reset}:R> · Weekly reset <t:{weekly_reset}:R>"
    assert fields(embed) == [
        ("Daily · 1/4 · reward: 20 AA",
         "✅ Kill 10 enemies · 10 AA\n▫️ Complete a dungeon · 10 AA"),
        ("Weekly · 2/14 · reward claimed", "▫️ [PvP] Win 5 matches · 3/5 · 50 AA"),
        ("Special", "🎁 Defeat a world boss · ready to claim · 30 AA"),
    ]
    assert embed["author"]["name"] == "Example.1234"
    assert embed["footer"]["text"] == "AA = Astral Acclaim"
    assert sorted(url for url, _ in requests) == sorted(
        API + f"account/wizardsvault/{p}" for p in ("daily", "weekly", "special")
    )


async def test_wizards_vault_shows_acclaim_with_wallet_permission():
    wallet = [{"id": 1, "value": 100}, {"id": 63, "value": 1234}]
    embed, requests = await subject.wizards_vault(
        DAILY, WEEKLY, SPECIAL, wallet=wallet, now=NOW, permissions=("account", "progression", "wallet")
    )
    assert fields(embed)[-1] == ("Astral Acclaim", "1234")
    assert requests[-1][0] == API + "account/wallet"


async def test_wizards_vault_skips_empty_lists():
    embed, _ = await subject.wizards_vault(period([], 0, 0), WEEKLY, {"objectives": []}, now=NOW)
    assert [name for name, _ in fields(embed)] == ["Weekly · 2/14 · reward claimed"]
