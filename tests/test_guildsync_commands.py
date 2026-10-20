"""/guildsync add, edit, toggle, purge and diagnose, the leader's authorization prompt, and the
rest of /server."""
import datetime

import pytest

import subject

API = "https://api.guildwars2.com/v2/"
INFO = {"id": "GUILD-A", "name": "Alpha Guild", "tag": "A"}
RANKS = [{"id": "Leader", "order": 1}, {"id": "Member", "order": 2}]
ROSTER = [{"name": "Leader.1111", "rank": "Leader"}, {"name": "Member.3333", "rank": "Member"}]
LEADER = {1: subject.accounts("Leader.1111")}


def found_guild():
    """guild/search, then guild/:id."""
    return [(200, ["GUILD-A"]), (200, INFO)]


# --- /guildsync add ----------------------------------------------------------------------------


async def test_add_with_your_own_key():
    server = subject.FakeServer()
    result = await subject.guildsync_command(
        "add", server, users=LEADER,
        responses=found_guild() + [(200, ROSTER), (200, RANKS), (200, ROSTER)],
        guild_name="alpha guild", sync_type="ranks_and_role", authentication_method="use_key",
    )
    assert result["replies"] == ["Guildsync succesfully added!"]
    [sync] = result["syncs"]
    assert {k: sync[k] for k in ("guild_id", "gid", "key", "enabled", "name", "tag")} == {
        "guild_id": 10, "gid": "GUILD-A", "key": "KEY-Leader.1111", "enabled": {"tag": True, "ranks": True},
        "name": "Alpha Guild", "tag": "A",
    }
    # Guild sync was already on for the server; the new sync runs at once
    assert result["settings"] == []
    assert server.created == ["Alpha Guild [A]", "Leader", "Member"]
    assert result["requests"][:3] == [API + "guild/search?name=Alpha%20Guild", API + "guild/GUILD-A",
                                      API + "guild/GUILD-A/members"]


async def test_first_sync_turns_guild_sync_on():
    result = await subject.guildsync_command(
        "add", subject.FakeServer(), users=LEADER, settings={}, responses=found_guild() + [(200, ROSTER)],
        guild_name="Alpha Guild", sync_type="ranks", authentication_method="use_key",
    )
    assert result["settings"] == [(10, "set", {"guildsync.enabled": True})]


async def test_add_needs_the_guild_leader():
    server = subject.FakeServer()
    result = await subject.guildsync_command(
        "add", server, users=LEADER, responses=found_guild() + [(403, {"text": "access restricted to guild leaders"})],
        guild_name="Alpha Guild", sync_type="ranks", authentication_method="use_key",
    )
    assert result["replies"] == ["You are not the guild leader."]
    assert result["syncs"] == []


async def test_add_with_an_entered_key():
    server = subject.FakeServer()
    result = await subject.guildsync_command(
        "add", server, responses=found_guild() + [(200, ROSTER), (200, ROSTER)],
        guild_name="Alpha Guild", sync_type="guild_role", authentication_method="enter_key", api_key="ENTERED",
    )
    assert result["replies"] == ["Guildsync succesfully added!"]
    assert result["syncs"][0]["key"] == "ENTERED"
    assert result["syncs"][0]["enabled"] == {"tag": True, "ranks": False}


async def test_add_an_unknown_guild():
    server = subject.FakeServer()
    result = await subject.guildsync_command(
        "add", server, users=LEADER, responses=[(200, [])],
        guild_name="Nobody", sync_type="ranks", authentication_method="use_key",
    )
    assert result["replies"] == ["Invalid guild name"]


@pytest.mark.parametrize("method, message", [
    ("prompt_user", "You must specify a user to prompt for authorization"),
    ("enter_key", "You must specify an API key to use for authorization"),
])
async def test_add_needs_the_method_argument(method, message):
    result = await subject.guildsync_command("add", subject.FakeServer(), guild_name="Alpha Guild",
                                             sync_type="ranks", authentication_method=method)
    assert result["replies"] == [message]


async def test_add_by_prompting_the_leader():
    from unittest.mock import AsyncMock, MagicMock

    server = subject.FakeServer()
    leader = MagicMock(id=2)
    leader.send = AsyncMock(return_value=MagicMock(id=555))
    users = {1: {}, 2: subject.accounts("Leader.1111")}
    result = await subject.guildsync_command(
        "add", server, users=users, responses=found_guild() + [(200, ROSTER)],
        guild_name="Alpha Guild", sync_type="ranks", authentication_method="prompt_user", user_to_prompt=leader,
    )
    assert result["replies"] == ["Message successfully sent. You will be notified when the user replies."]
    [prompt] = result["prompts"]
    assert {k: prompt[k] for k in ("guildsync_id", "guild_id", "requester_id", "message_id")} == {
        "guildsync_id": "GUILD-A", "guild_id": 10, "requester_id": 1, "message_id": 555,
    }
    assert result["syncs"] == []
    embed = leader.send.await_args.kwargs["embed"]
    assert embed.title == "Guildsync request"


# --- The authorization prompt -------------------------------------------------------------------

PROMPT = {"guildsync_id": "GUILD-A", "guild_id": 10, "requester_id": 1, "message_id": 555,
          "created_at": datetime.datetime(2024, 3, 5),
          "options": {"enabled": {"tag": False, "ranks": True}, "name": "Alpha Guild", "tag": "A"}}


async def test_leader_confirms():
    server = subject.FakeServer()
    result = await subject.answer_guildsync_prompt(
        server, True, users={2: subject.accounts("Leader.1111")}, prompts=[PROMPT],
        responses=[(200, ROSTER), (200, RANKS), (200, ROSTER)],
    )
    assert result["reply"] == "Guildsync successfully enabled! Thank you."
    assert result["syncs"][0]["key"] == "KEY-Leader.1111"
    assert result["requester"][0].startswith("User ")
    assert result["requester"][1:] == ["Guildsync succesfully added!"]
    assert result["prompts"] == []
    assert result["deleted"]


async def test_leader_denies():
    result = await subject.answer_guildsync_prompt(subject.FakeServer(), False, users={}, prompts=[PROMPT])
    assert result["reply"].startswith("Noted, request rejected.")
    assert result["prompts"] == result["syncs"] == []


# --- /guildsync edit, toggle, purge, diagnose ----------------------------------------------------


async def test_edit_toggles_ranks():
    server = subject.FakeServer()
    result = await subject.guildsync_command(
        "edit", server, syncs=[subject.guildsync_doc(tag=False)], responses=[(200, ROSTER)],
        sync="GUILD-A", operation="ranks",
    )
    [embed] = result["replies"]
    assert embed["title"] == "Post-update Alpha Guild [A] settings"
    assert embed["description"] == "Syncing ranks: **OFF**\nGuild role for members: **OFF**"
    assert result["syncs"][0]["enabled"] == {"ranks": False, "tag": False}


async def test_edit_changes_the_key():
    server = subject.FakeServer()
    result = await subject.guildsync_command(
        "edit", server, syncs=[subject.guildsync_doc(tag=False)], responses=[(200, ROSTER), (200, RANKS),
                                                                               (200, ROSTER)],
        sync="GUILD-A", operation="change_key", api_key="NEW",
    )
    assert result["syncs"][0]["key"] == "NEW"


async def test_edit_deletes_the_sync_and_its_roles():
    server = subject.FakeServer()
    tag, member = server.role("Alpha Guild [A]"), server.role("Member")
    sync = subject.guildsync_doc(rank_roles={"Member": member.id}, tag_role=tag.id)
    result = await subject.guildsync_command("edit", server, syncs=[sync], sync="GUILD-A", operation="delete")
    assert result["replies"] == ["Sync successfully deleted"]
    assert result["syncs"] == []
    assert sorted(server.deleted) == ["Alpha Guild [A]", "Member"]


async def test_edit_an_unknown_sync():
    result = await subject.guildsync_command("edit", subject.FakeServer(), sync="NOPE", operation="ranks")
    assert result["replies"] == ["No valid sync chosen"]


async def test_toggle():
    result = await subject.guildsync_command("toggle", subject.FakeServer(), enabled=False)
    assert result["replies"][0].startswith("Guildsync is now disabled globally on this server.")
    assert result["settings"] == [(10, "set", {"guildsync.enabled": False})]


@pytest.mark.parametrize("confirm, writes", [
    (True, [(10, "set", {"guildsync.purge": True})]),
    (False, []),
])
async def test_purge_needs_confirming(confirm, writes):
    result = await subject.guildsync_command("purge", subject.FakeServer(), enabled=True, confirm=confirm)
    assert result["replies"][0].startswith("Members without any other role that have been in the server")
    assert result["settings"] == writes


async def test_purge_off():
    result = await subject.guildsync_command("purge", subject.FakeServer(), enabled=False)
    assert result["replies"] == ["Disabled purge."]
    assert result["settings"] == [(10, "set", {"guildsync.purge": False})]


async def test_diagnose_all_good():
    server = subject.FakeServer()
    result = await subject.guildsync_command(
        "diagnose", server, syncs=[subject.guildsync_doc(tag=False)],
        responses=[(200, ROSTER), (200, RANKS)], sync="GUILD-A",
    )
    assert result["replies"][0].startswith("Everything seems to be in order!")


async def test_diagnose_a_revoked_key():
    result = await subject.guildsync_command(
        "diagnose", subject.FakeServer(), syncs=[subject.guildsync_doc()], responses=[(401, {"text": "x"})],
        sync="GUILD-A",
    )
    assert result["replies"] == ["The added key is no longer valid. Please change the key using /guildsync edit."]


async def test_diagnose_a_role_above_the_bot():
    server = subject.FakeServer()
    high = server.role("Leader", position=60)
    sync = subject.guildsync_doc(tag=False, rank_roles={"Leader": high.id})
    result = await subject.guildsync_command("diagnose", server, syncs=[sync],
                                             responses=[(200, ROSTER), (200, RANKS)], sync="GUILD-A")
    assert result["replies"][0].startswith("The synced role <role Leader> is higher on the hierarchy")


# --- /server ------------------------------------------------------------------------------------


async def test_force_account_names():
    server = subject.FakeServer()
    replies, writes, started = await subject.server_command("force_account_names", server, enabled=True)
    assert replies[0].startswith("Automatic account names enabled.")
    assert writes == [(10, "set", {"force_account_names": True})]
    assert started == ["rename"]


async def test_sync_now():
    replies, _, started = await subject.server_command("sync_now", subject.FakeServer())
    assert replies == ["Syncs scheduled!"]
    assert started == ["guildsync"]


async def test_default_guild():
    replies, writes, _ = await subject.server_command("default_guild", subject.FakeServer(),
                                                      responses=[(200, INFO)], guild="GUILD-A")
    assert replies[0].startswith("Your default guild is now set to Alpha Guild for this server.")
    assert writes == [(10, "set", {"guild_ingame": "GUILD-A"})]


async def test_forced_account_names_loop():
    server = subject.FakeServer()
    for member_id in 1, 2, 3:
        server.member(member_id)
    server.members[1].display_name = "Leader.1111 (Leader)"
    users = {1: subject.accounts("Member.3333"), 2: subject.accounts("Leader.1111")}
    # Already contains their account name, or has no key
    assert await subject.run_forced_account_names(server, users) == {1: "Member.3333"}


# --- Fixes ------------------------------------------------------------------------------------------


async def test_diagnose_a_user_with_several_accounts():
    from unittest.mock import MagicMock

    users = {5: subject.accounts("Other.9999", "Member.3333")}
    result = await subject.guildsync_command(
        "diagnose", subject.FakeServer(), users=users, syncs=[subject.guildsync_doc(tag=False)],
        responses=[(200, ROSTER), (200, RANKS), (200, ROSTER)], sync="GUILD-A", user=MagicMock(id=5),
    )
    assert result["replies"][0].startswith("Everything seems to be in order!")


async def test_diagnose_a_user_without_keys():
    from unittest.mock import MagicMock

    result = await subject.guildsync_command(
        "diagnose", subject.FakeServer(), users={5: {}}, syncs=[subject.guildsync_doc(tag=False)],
        responses=[(200, ROSTER), (200, RANKS), (200, ROSTER)], sync="GUILD-A", user=MagicMock(id=5),
    )
    assert result["replies"] == ["The provided user is not in the guild."]


async def test_edit_change_key_needs_a_key():
    result = await subject.guildsync_command("edit", subject.FakeServer(), syncs=[subject.guildsync_doc()],
                                             sync="GUILD-A", operation="change_key")
    assert result["replies"] == ["You must fill the API key argument to use this operation."]


async def test_leader_answers_an_expired_prompt():
    result = await subject.answer_guildsync_prompt(subject.FakeServer(), True,
                                                   users={2: subject.accounts("Leader.1111")})
    assert result["reply"] == "This request has expired."


async def test_force_account_names_replies_first():
    replies, _, started = await subject.server_command("force_account_names", subject.FakeServer(), enabled=True)
    assert "`/server force_account_names enabled:False`" in replies[0]
    assert started == ["rename"]
