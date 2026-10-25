"""The owner's repair for ranks whose roles guild sync replaced (relink
each rank to its old role, and delete the replacement), and the report of
what guild sync sees in a server."""
from bson import ObjectId

import subject

SYNC_ID = ObjectId("61ca24a1fb1f3791e99d2e12")


def replaced_server():
    """Server 10 with the old Leader and Member roles, the replacements
    guild sync created for them, and a member with both Leader roles."""
    server = subject.FakeServer()
    old = {"Leader": server.role("Leader", role_id=201), "Member": server.role("Member", role_id=202)}
    new = {"Leader": server.role("Leader", role_id=301), "Member": server.role("Member", role_id=302)}
    server.member(1, old["Leader"], new["Leader"])
    return server, old, new


def sync(rank_roles=None, **extra):
    return subject.guildsync_doc(_id=SYNC_ID, tag=False, rank_roles=rank_roles or {"Leader": 301, "Member": 302},
                                 **extra)


def entry(roles=None, guild_id=10, sync_id=SYNC_ID):
    return {"sync": str(sync_id), "guild_id": str(guild_id),
            "roles": roles or {"Leader": ["201", "301"], "Member": ["202", "302"]}}


async def test_dry_run_changes_nothing():
    server, _, _ = replaced_server()
    counts, lines, syncs = await subject.repair_replaced_roles(server, [sync()], [entry()])
    assert counts == {"sync repaired": 1, "rank relinked": 2}
    assert lines == [f"10 {SYNC_ID}: repaired - relinked Leader, Member"]
    assert syncs[0]["rank_roles"] == {"Leader": 301, "Member": 302}
    assert server.deleted == []


async def test_apply_relinks_the_old_roles_and_deletes_the_replacements():
    server, old, _ = replaced_server()
    counts, _, syncs = await subject.repair_replaced_roles(server, [sync()], [entry()], apply=True)
    assert counts == {"sync repaired": 1, "rank relinked": 2, "replacement deleted": 2}
    assert syncs[0]["rank_roles"] == {"Leader": 201, "Member": 202}
    assert sorted(server.roles) == [201, 202]
    # Members keep their old roles; the next sync fixes the rest
    assert server.members[0].role_names() == ["Leader"]
    assert server.members[0].roles[1] is old["Leader"]


async def test_ranks_that_cannot_be_relinked_are_kept():
    server, old, _ = replaced_server()
    server.role("Officer", role_id=303)
    server.role("Veteran", role_id=204, position=60)
    server.role("Veteran", role_id=304)
    old["Leader"].position = 50
    rank_roles = {"Leader": 301, "Member": 999, "Officer": 303, "Veteran": 304}
    roles = {"Leader": ["201", "301"], "Member": ["202", "302"], "Officer": ["203", "303"],
             "Veteran": ["204", "304"]}
    counts, lines, syncs = await subject.repair_replaced_roles(server, [sync(rank_roles)], [entry(roles)],
                                                               apply=True)
    assert counts == {"sync nothing to relink": 1, "rank relinked": 0,
                      "rank kept: old role above the bot's": 2, "rank kept: changed since": 1,
                      "rank kept: old role deleted": 1}
    assert lines == [f"10 {SYNC_ID}: nothing to relink - kept Leader (old role above the bot's), "
                     "Member (changed since), Officer (old role deleted), Veteran (old role above the bot's)"]
    assert syncs[0]["rank_roles"] == rank_roles
    assert server.deleted == []


async def test_syncs_that_cannot_be_repaired_are_skipped():
    server, _, _ = replaced_server()
    entries = [entry(guild_id=11), entry(sync_id=ObjectId("61ca24a1fb1f3791e99d2e13"))]
    counts, lines, _ = await subject.repair_replaced_roles(server, [sync()], entries, apply=True)
    assert counts == {"sync bot not in server": 1, "sync sync removed": 1}
    assert lines == [f"11 {SYNC_ID}: bot not in server", "10 61ca24a1fb1f3791e99d2e13: sync removed"]

    server = subject.FakeServer(can_manage_roles=False)
    counts, _, _ = await subject.repair_replaced_roles(server, [sync()], [entry()], apply=True)
    assert counts == {"sync can't manage roles": 1}


async def test_a_server_syncs_one_at_a_time():
    server, _, _ = replaced_server()
    waited, ran = await subject.sync_while_locked(server, [sync()])
    assert waited == []
    assert ran


# --- >guildsync_repair ------------------------------------------------------------------------


async def test_owner_command_is_a_dry_run_unless_applied():
    mapping = b'[{"sync": "SYNC"}]'
    applied, reply, report = await subject.owner_guildsync_repair("dry-run", mapping)
    assert applied is False
    assert reply == "Dry run, nothing changed:\n```\nrank relinked: 1\nsync repaired: 1\n```"
    assert report == "10 SYNC: repaired - relinked Leader"
    applied, reply, _ = await subject.owner_guildsync_repair("apply", mapping)
    assert applied is True
    assert reply.startswith("Applied:")


async def test_owner_command_needs_the_mapping():
    applied, reply, _ = await subject.owner_guildsync_repair("apply")
    assert applied is None
    assert reply == "Attach the JSON file of roles to relink"


# --- >guildsync_inspect -----------------------------------------------------------------------


async def test_inspect_shows_what_guild_sync_sees():
    server, old, new = replaced_server()
    server.uncached.add(old["Leader"].id)
    ranks = [{"id": "Leader", "order": 1}, {"id": "Member ", "order": 2}]
    report = await subject.inspect_guildsync(server, [sync({"Leader": 201, "Member": 302})], [(200, ranks)])
    assert report.splitlines() == [
        "Server 'Example Server' (10), chunked: True",
        "Bot's top role: 'GW2Bot' at 50, manage roles: True",
        "Roles cached: 4, on Discord: 5",
        "Guild sync enabled: True, purge: None",
        "",
        f"Sync {SYNC_ID}: 'Alpha Guild' [A] GUILD-A",
        "  enabled: {'ranks': True, 'tag': False}, error: None",
        "  rank roles saved:",
        "    'Leader' -> 201 (int): cache: MISSING | Discord: 'Leader' at 10, 1 members",
        "    'Member' -> 302 (int): cache: 'Member' at 10, 0 members | Discord: 'Member' at 10, 0 members",
        "  in-game ranks: ['Leader', 'Member ']",
        "  roles on Discord named like a rank:",
        "    201: 'Leader' at 10, 1 members, cached: False",
        "    301: 'Leader' at 10, 1 members, cached: True",
        "    202: 'Member' at 10, 0 members, cached: True",
        "    302: 'Member' at 10, 0 members, cached: True",
    ]
    assert "LEADER" not in report
