"""Event reminders: when they fire, and what they send."""
import datetime
import threading

import subject

UTC = datetime.timezone.utc
NOW = datetime.datetime(2024, 3, 6, 12, tzinfo=UTC)


def finishes(function, *args, seconds=2):
    """(finished in time, result). The work runs in a daemon thread, so a
    hang fails the test instead of the run."""
    result = []
    thread = threading.Thread(target=lambda: result.append(function(*args)), daemon=True)
    thread.start()
    thread.join(seconds)
    return not thread.is_alive(), result[0] if result else None


def test_boss_missing_from_the_schedule_doesnt_hang():
    # E.g. a reminder for a boss since renamed or removed in the game data
    done, seconds = finishes(subject.seconds_until_boss, "Renamed Boss", NOW)
    assert done
    assert seconds is None


def test_known_boss_still_found():
    done, seconds = finishes(subject.seconds_until_boss, "Shadow Behemoth", NOW)
    assert done
    assert 0 < seconds <= 2 * 3600


# --- /reminder event --------------------------------------------------------------


async def test_reminder_for_a_boss():
    sent, writes = await subject.set_event_reminder(event_name="shadow behemoth", minutes_before_event=10)
    assert sent == "Reminder set succesfully"
    assert writes == [(1, "push", {"event_reminders": {"type": "boss", "name": "Shadow Behemoth", "time": 600}})]


async def test_reminder_for_a_map_event():
    sent, writes = await subject.set_event_reminder(event_name="Gerent Preparation")
    assert sent == "Reminder set succesfully"
    assert writes == [(1, "push", {"event_reminders": {
        "type": "phase", "name": "Gerent Preparation", "group": "hot", "map_name": "Tangled Depths", "time": 300,
    }})]


async def test_reminder_for_a_secrets_of_the_obscure_event():
    sent, writes = await subject.set_event_reminder(event_name="Fly by Night")
    assert sent == "Reminder set succesfully"
    assert writes == [(1, "push", {"event_reminders": {
        "type": "phase", "name": "Fly by Night", "group": "soto", "map_name": "Wizard's Tower", "time": 300,
    }})]


async def test_reminder_for_an_unknown_event():
    sent, writes = await subject.set_event_reminder(event_name="Nothing")
    assert sent == "No event found matching that name"
    assert writes == []
