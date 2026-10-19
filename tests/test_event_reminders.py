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
