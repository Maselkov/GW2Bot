"""The daily notifier's posting behaviours and pinning."""
import pytest

import subject


async def test_new_message_each_day():
    events = await subject.run_daily_notifier({})
    assert events["sent"] == [1001]
    assert events["deleted"] == events["edited"] == events["pinned"] == []
    assert events["writes"] == [(10, "set", {"daily.message": 1001})]


async def test_autodelete_replaces_the_previous_message():
    events = await subject.run_daily_notifier({"autodelete": True})
    assert (events["sent"], events["deleted"]) == ([1001], [999])


async def test_autoedit_edits_the_previous_message():
    events = await subject.run_daily_notifier({"autoedit": True})
    assert (events["sent"], events["edited"]) == ([], [999])
    assert events["writes"] == []


async def test_autoedit_posts_anew_when_the_previous_message_is_gone():
    events = await subject.run_daily_notifier({"autoedit": True}, previous_message_exists=False)
    assert (events["sent"], events["edited"]) == ([1001], [])


async def test_autopin_with_autoedit_pins_the_edited_message():
    events = await subject.run_daily_notifier({"autoedit": True, "autopin": True})
    assert events["pinned"] == [999]


@pytest.mark.parametrize("behaviour", [{}, {"autodelete": True}])
async def test_autopin_pins_the_new_message(behaviour):
    events = await subject.run_daily_notifier({**behaviour, "autopin": True})
    assert events["sent"] == [1001]
    assert events["pinned"] == [1001]
    if not behaviour:
        # The previous day's message stays, unpinned
        assert events["unpinned"] == [999]


# --- Permissions --------------------------------------------------------------------------


async def test_skips_a_deleted_channel():
    events = await subject.run_daily_notifier({}, channel_exists=False)
    assert events["sent"] == events["texts"] == events["writes"] == []


async def test_skips_a_channel_it_cant_send_to():
    events = await subject.run_daily_notifier({}, can_send=False)
    assert events["sent"] == events["texts"] == []


async def test_asks_for_embed_permission():
    events = await subject.run_daily_notifier({}, can_embed=False)
    assert events["texts"] == ["Need permission to embed links in order to send daily notifs!"]
    assert events["sent"] == []


async def test_posts_tomorrows_dailies():
    events = await subject.run_daily_notifier({"categories": ["raids"]})
    [embed] = events["embeds"]
    assert embed["title"] == "Dailies"
    # Midnight UTC, when they start
    assert embed["timestamp"].endswith("T00:00:00+00:00")


# --- The dailies cache --------------------------------------------------------------------


CATEGORIES = [
    {"id": 88, "achievements": [{"id": 1}, {"id": 2}], "tomorrow": [{"id": 3}]},
    {"id": 475, "achievements": [{"id": 4}], "tomorrow": [{"id": 4}]},
    {"id": 238, "achievements": [], "tomorrow": []},
    {"id": 243, "achievements": [], "tomorrow": []},
]
NAMES = [
    {"id": 1, "name": "Daily Tier 4 Aquatic Ruins"},
    {"id": 2, "name": "Daily Tier 1 Aquatic Ruins"},
    {"id": 3, "name": "Daily Tier 4 Volcanic"},
    {"id": 4, "name": "Raid Bounty: Vale Guardian"},
]


async def test_dailies_refresh_caches_today_and_tomorrow():
    writes, error = await subject.run_dailies_refresh([(200, CATEGORIES), (200, NAMES)])
    assert error is None
    assert writes == [{
        "cache.dailies": {"fractals": ["Daily Tier 4 Aquatic Ruins"], "raids": ["Raid Bounty: Vale Guardian"],
                          "lws3": [], "lws4": []},
        "cache.dailies_tomorrow": {"fractals": ["Daily Tier 4 Volcanic"], "raids": ["Raid Bounty: Vale Guardian"],
                                   "lws3": [], "lws4": []},
    }]


async def test_dailies_refresh_keeps_the_cache_on_errors(caplog):
    writes, error = await subject.run_dailies_refresh([(500, {"text": "error"})])
    assert error is None
    assert writes == []
    assert "Couldn't cache dailies" in caplog.text
