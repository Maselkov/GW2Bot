"""Guild sync purge: kicking members who aren't in any synced guild."""
import pytest

import subject

ROSTER = [{"name": "Member.1111", "rank": "Member"}]


def server():
    return [
        subject.discord_member(1),  # in the guild
        subject.discord_member(2),  # has a key, not in the guild
        subject.discord_member(3),  # no key
        subject.discord_member(4, roles=2),  # not in the guild, but has a role
        subject.discord_member(5, days_on_server=1),  # joined less than 48 hours ago
    ]


ACCOUNTS = {1: "Member.1111", 2: "Other.2222", 4: "Other.4444", 5: "Other.5555"}


async def test_purge_kicks_members_in_no_synced_guild():
    kicked = await subject.run_guildsync(server(), ACCOUNTS, [(200, ROSTER)])
    assert kicked == [2, 3]


async def test_no_purge_when_disabled():
    assert await subject.run_guildsync(server(), ACCOUNTS, [(200, ROSTER)], purge=False) == []


async def test_membership_in_any_sync_counts():
    roster_2 = [{"name": "Other.2222", "rank": "Member"}]
    kicked = await subject.run_guildsync(server(), ACCOUNTS, [(200, ROSTER), (200, roster_2)], syncs=2)
    assert kicked == [3]


@pytest.mark.parametrize("failure", [
    (500, {"text": "internal error"}),
    (403, {"text": "access restricted to guild leaders"}),
    (400, {"text": "Invalid access token"}),
])
async def test_no_purge_when_a_member_list_cant_be_read(failure):
    # The API being down, or the key losing leader access, must not look
    # like everyone left the guild
    assert await subject.run_guildsync(server(), ACCOUNTS, [failure]) == []


async def test_no_purge_when_any_sync_fails():
    kicked = await subject.run_guildsync(server(), ACCOUNTS, [(200, ROSTER), (500, {"text": "error"})], syncs=2)
    assert kicked == []


async def test_no_purge_without_any_syncs():
    assert await subject.run_guildsync(server(), ACCOUNTS, [], syncs=0) == []
