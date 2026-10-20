"""Background work: errors are logged instead of lost, nothing is retried forever, and syncs read
each server's users once."""
import datetime

import pytest

import subject

UTC = datetime.timezone.utc
BASE = datetime.datetime(2024, 3, 6, 12, tzinfo=UTC)


# --- Background tasks --------------------------------------------------------------------------


async def test_background_work_is_held_and_its_errors_logged(caplog):
    async def fails():
        raise RuntimeError("boom")

    assert await subject.run_in_background(fails, "posting dailies to 10")
    assert "Error in the background: posting dailies to 10" in caplog.text
    assert "RuntimeError: boom" in caplog.text


async def test_daily_notifier_errors_are_logged(caplog):
    events = await subject.run_daily_notifier({}, error=RuntimeError("Discord is down"))
    assert events["sent"] == []
    assert "Error in the background: posting dailies to server 10" in caplog.text


# --- Undeliverable DMs -----------------------------------------------------------------------------


def behemoth_spawn():
    return next(time for name, time in subject.upcoming_bosses(BASE, limit=40) if name == "Shadow Behemoth")


async def test_reminder_isnt_retried_when_dms_are_closed():
    spawn = behemoth_spawn()
    reminder = {"type": "boss", "name": "Shadow Behemoth", "time": 600}
    dms, writes = await subject.run_reminder(reminder, spawn - datetime.timedelta(minutes=10), can_dm=False)
    assert dms.sent == []
    # Counted as reminded for this spawn, so the next checks skip it
    [(user, op, fields)] = writes
    saved = fields["event_reminders.0"]
    assert saved["last_reminded"] == (spawn - datetime.timedelta(minutes=10)).replace(tzinfo=None)
    assert "last_message" not in saved


async def test_gem_tracker_stops_tracking_for_users_it_cant_dm():
    price = (200, {"coins_per_gem": 2500, "quantity": 4000})
    sent, writes, error = await subject.run_gem_tracker([price], {950: 1_100_000})
    assert error is None
    assert sent == []
    assert writes == [(950, "set", {"gemtrack": None})]


# --- Boss notifier ------------------------------------------------------------------------------------


async def test_boss_notifier_turns_off_where_it_cant_post():
    channel = subject.RecordingChannel(can_send=False)
    servers = {10: {"bossnotifs": {"on": True, "channel": 5}}}
    writes = await subject.run_boss_notifier(servers, [channel], BASE)
    assert writes == [(10, "set", {"bossnotifs.on": False})]


async def test_boss_notifier_errors_are_logged(caplog):
    channel = subject.RecordingChannel(error=RuntimeError("Discord is down"))
    servers = {10: {"bossnotifs": {"on": True, "channel": 5}}}
    await subject.run_boss_notifier(servers, [channel], BASE)
    assert "Couldn't post boss notifications in server 10" in caplog.text


# --- One read of the users per server ---------------------------------------------------------------


def members(*accounts):
    server = subject.FakeServer()
    users = {}
    for member_id, account in enumerate(accounts, start=1):
        server.member(member_id)
        users[member_id] = subject.accounts(account)
    return server, users


@pytest.mark.parametrize("job", ["guild sync", "key role", "forced names"])
async def test_syncs_read_the_users_once(job):
    server, users = members("Member.3333", "Other.4444", "Third.5555")
    responses = [(200, [{"name": "Member.3333", "rank": "Member"}])]
    reads = await subject.user_reads(job, server, users, responses=responses,
                                     syncs=[subject.guildsync_doc(ranks=False, tag=False)])
    assert [kind for kind, _ in reads] == ["find"]
    assert reads[0][1] == {"_id": {"$in": [1, 2, 3]}}


async def test_the_api_key_role_still_follows_keys():
    role = subject.KEY_ROLE
    members_ = [subject.server_member(1), subject.server_member(2, role)]
    changes = await subject.run_key_role_sync(members_, {1: {"key": subject.api_key("A")}, 2: {}})
    assert changes == {1: [("add", [77])], 2: [("remove", [77])]}


# --- EVTC ---------------------------------------------------------------------------------------------


async def test_autopost_skips_users_who_left_quietly(caplog):
    from test_evtc import NOTIFICATION, destination, report

    channel = subject.RecordingChannel(6, 11)
    await subject.run_evtc_autopost([NOTIFICATION], [destination(6)], {"abc-123": report()}, [channel],
                                    members={6: []})
    assert channel.sent == []
    assert "Exception" not in caplog.text
