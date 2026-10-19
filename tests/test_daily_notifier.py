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
