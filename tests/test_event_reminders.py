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


# --- Firing reminders ---------------------------------------------------------------

BASE = datetime.datetime(2024, 3, 6, 12, tzinfo=UTC)


def next_spawn(boss):
    return next(time for name, time in subject.upcoming_bosses(BASE, limit=40) if name == boss)


SPAWN = next_spawn("Shadow Behemoth")
BEHEMOTH = {"type": "boss", "name": "Shadow Behemoth", "time": 600}


async def test_reminder_fires_before_the_event():
    dms, writes = await subject.run_reminder(BEHEMOTH, SPAWN - datetime.timedelta(minutes=10))
    [(content, embed, view)] = dms.sent
    assert embed["title"] == "Event reminder"
    assert embed["description"] == f"Shadow Behemoth will begin <t:{int(SPAWN.timestamp())}:R>"
    assert [item.custom_id for item in view.children] == ["et:unsubscribe"]
    assert writes == [(1, "set", {"event_reminders.0": {
        **BEHEMOTH, "last_reminded": datetime.datetime(2024, 3, 6, 12, tzinfo=UTC), "last_message": 1001,
    }})]


async def test_reminder_waits_until_its_time():
    dms, writes = await subject.run_reminder(BEHEMOTH, SPAWN - datetime.timedelta(minutes=11))
    assert dms.sent == writes == []


async def test_reminder_isnt_repeated_for_the_same_spawn():
    now = SPAWN - datetime.timedelta(minutes=9)
    reminded = {**BEHEMOTH, "last_reminded": (now - datetime.timedelta(minutes=1)).replace(tzinfo=None)}
    dms, writes = await subject.run_reminder(reminded, now)
    assert dms.sent == writes == []


async def test_reminder_replaces_the_previous_dm():
    dms, _ = await subject.run_reminder({**BEHEMOTH, "last_message": 500}, SPAWN - datetime.timedelta(minutes=10),
                                        existing=[500])
    assert dms.deleted == [500]
    assert len(dms.sent) == 1


async def test_unsubscribe():
    reply, writes, deleted = await subject.press_unsubscribe(1001)
    assert reply == "Unsubscribed!"
    assert writes == [(1, "pull", {"event_reminders": {"last_message": 1001}})]
    assert deleted


# --- /et ------------------------------------------------------------------------------


async def test_et_bosses():
    embed = await subject.et_command("bosses", BASE)
    assert embed["title"] == "Upcoming world bosses"
    assert len(embed["fields"]) == 8
    first = subject.upcoming_bosses(BASE, limit=1)[0]
    assert embed["fields"][0]["name"].startswith(f"{first[0]} in ")


async def test_et_map_timers():
    embed = await subject.et_command("soto", BASE)
    assert embed["title"] == "Secrets of the Obscure"
    assert [f["name"] for f in embed["fields"]] == ["Skywatch Archipelago", "Wizard's Tower", "Amnytas",
                                                    "Inner Nayos"][:len(embed["fields"])]


# --- Boss notifier -------------------------------------------------------------------------


def boss_servers(**settings):
    return {10: {"bossnotifs": {"on": True, "channel": 5, **settings}}}


async def test_boss_notifier_posts_and_deletes_the_previous_post():
    channel = subject.RecordingChannel(existing=[999])
    writes = await subject.run_boss_notifier(boss_servers(message=999), [channel], BASE)
    [(_, embed, _)] = channel.sent
    assert embed["title"] == "Upcoming world bosses"
    assert len(embed["fields"]) == 2
    assert channel.deleted == [999]
    assert writes == [(10, "set", {"bossnotifs.message": 1001})]


async def test_boss_notifier_edits():
    channel = subject.RecordingChannel(existing=[999])
    writes = await subject.run_boss_notifier(boss_servers(message=999, edit=True), [channel], BASE)
    assert (channel.sent, channel.edited, channel.deleted, writes) == ([], [999], [], [])


async def test_boss_notifier_edit_posts_anew_when_the_message_is_gone():
    channel = subject.RecordingChannel()
    writes = await subject.run_boss_notifier(boss_servers(message=999, edit=True), [channel], BASE)
    assert len(channel.sent) == 1
    assert writes == [(10, "set", {"bossnotifs.message": 1001})]


async def test_boss_notifier_asks_for_embed_permission():
    channel = subject.RecordingChannel(can_embed=False)
    writes = await subject.run_boss_notifier(boss_servers(), [channel], BASE)
    assert [content for content, _, _ in channel.sent] == [
        "Need permission to embed links in order to send boss notifs!",
    ]
    assert writes == []


async def test_boss_notifier_skips_deleted_channels_and_disabled_servers():
    channel = subject.RecordingChannel(channel_id=6, guild_id=11)
    servers = {**boss_servers(), 11: {"bossnotifs": {"on": False, "channel": 6}}}
    assert await subject.run_boss_notifier(servers, [channel], BASE) == []
    assert channel.sent == []
