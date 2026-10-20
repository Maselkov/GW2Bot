"""Guild sync: the roles it creates and deletes, and who gets which."""
import subject

API = "https://api.guildwars2.com/v2/"
RANKS = [{"id": "Leader", "order": 1}, {"id": "Officer", "order": 2}, {"id": "Member", "order": 3}]
ROSTER = [
    {"name": "Leader.1111", "rank": "Leader"},
    {"name": "Officer.2222", "rank": "Officer"},
    {"name": "Member.3333", "rank": "Member"},
    {"name": "Alt.4444", "rank": "Member"},
]


# --- Roles ------------------------------------------------------------------------------------


async def test_first_sync_creates_the_roles():
    server = subject.FakeServer()
    syncs, requests = await subject.sync_server(server, {}, [(200, RANKS), (200, ROSTER)],
                                                [subject.guildsync_doc()])
    # The guild's tag role, then one per rank
    assert server.created == ["Alpha Guild [A]", "Leader", "Officer", "Member"]
    [sync] = syncs
    roles = {r.name: r.id for r in server.roles.values()}
    assert sync["tag_role"] == roles["Alpha Guild [A]"]
    assert sync["rank_roles"] == {"Leader": roles["Leader"], "Officer": roles["Officer"], "Member": roles["Member"]}
    assert requests == [API + "guild/GUILD-A/ranks", API + "guild/GUILD-A/members"]


async def test_existing_roles_are_kept_and_old_ranks_deleted():
    server = subject.FakeServer()
    leader, veteran = server.role("Leader"), server.role("Veteran")
    sync = subject.guildsync_doc(tag=False, rank_roles={"Leader": leader.id, "Veteran": veteran.id})
    syncs, _ = await subject.sync_server(server, {}, [(200, RANKS), (200, ROSTER)], [sync])
    assert server.created == ["Officer", "Member"]
    # A rank that no longer exists in game
    assert server.deleted == ["Veteran"]
    assert syncs[0]["rank_roles"]["Leader"] == leader.id
    assert "Veteran" not in syncs[0]["rank_roles"]


async def test_turned_off_features_delete_their_roles():
    server = subject.FakeServer()
    tag, member = server.role("Alpha Guild [A]"), server.role("Member")
    sync = subject.guildsync_doc(ranks=False, tag=False, rank_roles={"Member": member.id}, tag_role=tag.id)
    syncs, requests = await subject.sync_server(server, {}, [(200, ROSTER)], [sync])
    assert sorted(server.deleted) == ["Alpha Guild [A]", "Member"]
    assert syncs[0]["tag_role"] is None
    # Ranks off: no ranks request
    assert requests == [API + "guild/GUILD-A/members"]


async def test_an_api_error_is_saved_for_diagnose():
    server = subject.FakeServer()
    syncs, _ = await subject.sync_server(server, {}, [(401, {"text": "Invalid access token"})],
                                         [subject.guildsync_doc(tag=False)])
    assert syncs[0]["error"] == "Invalid key. Most likely deleted"
    assert server.created == []


# --- Members ----------------------------------------------------------------------------------


def synced_server():
    server = subject.FakeServer()
    roles = {name: server.role(name) for name in ("Alpha Guild [A]", "Leader", "Officer", "Member")}
    sync = subject.guildsync_doc(rank_roles={r: roles[r].id for r in ("Leader", "Officer", "Member")},
                                 tag_role=roles["Alpha Guild [A]"].id)
    return server, roles, sync


async def test_members_get_their_highest_rank_and_the_tag():
    server, roles, sync = synced_server()
    officer = server.member(1, roles["Member"])  # promoted in game
    two_accounts = server.member(2)  # a Member account and the Leader account
    outsider = server.member(3, roles["Member"], roles["Alpha Guild [A]"])  # left the guild
    no_key = server.member(4)
    users = {1: subject.accounts("Officer.2222"), 2: subject.accounts("Member.3333", "Leader.1111"),
             3: subject.accounts("Gone.9999")}
    await subject.sync_server(server, users, [(200, RANKS), (200, ROSTER)], [sync])
    assert officer.role_names() == ["Alpha Guild [A]", "Officer"]
    assert two_accounts.role_names() == ["Alpha Guild [A]", "Leader"]
    assert outsider.role_names() == []
    assert no_key.role_names() == []


async def test_roles_above_the_bot_arent_given():
    server, roles, sync = synced_server()
    roles["Leader"].position = 60  # above the bot's top role
    leader = server.member(1)
    await subject.sync_server(server, {1: subject.accounts("Leader.1111")}, [(200, RANKS), (200, ROSTER)], [sync])
    assert leader.role_names() == ["Alpha Guild [A]"]


async def test_member_join_syncs_just_them():
    server, roles, sync = synced_server()
    member = server.member(1)
    requests = await subject.member_joins_synced_server(
        server, member, {1: subject.accounts("Member.3333")}, [(200, RANKS), (200, ROSTER)], [sync]
    )
    assert member.role_names() == ["Alpha Guild [A]", "Member"]
    assert requests == [API + "guild/GUILD-A/ranks", API + "guild/GUILD-A/members"]


async def test_disabled_servers_arent_synced():
    server, roles, sync = synced_server()
    member = server.member(1)
    requests = await subject.run_guild_synchronizer(
        server, {1: subject.accounts("Member.3333")}, [(200, RANKS), (200, ROSTER)], [sync],
        settings={"guildsync": {"enabled": False}},
    )
    assert requests == []
    assert member.role_names() == []


async def test_the_loop_syncs_enabled_servers():
    server, roles, sync = synced_server()
    member = server.member(1)
    await subject.run_guild_synchronizer(server, {1: subject.accounts("Member.3333")},
                                         [(200, RANKS), (200, ROSTER)], [sync])
    assert member.role_names() == ["Alpha Guild [A]", "Member"]
