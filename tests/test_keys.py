"""/key add, remove, switch and info, and the API key role."""
import pytest

import subject

API = "https://api.guildwars2.com/v2/"
TOKEN_INFO = {"id": "A", "name": "Main", "permissions": ["account", "characters", "progression"]}
ACCOUNT = {"name": "Example.1234"}
key = subject.api_key


# --- /key add ---------------------------------------------------------------------------------


async def test_add_first_key():
    sent, writes, syncs = await subject.key_command("add", {}, [(200, TOKEN_INFO), (200, ACCOUNT)], token="A")
    added = key("A", name="Main", permissions=TOKEN_INFO["permissions"])
    assert writes == [(1, "set", {"key": added, "keys": [added]})]
    assert sent.startswith("Your key was verified and associated with your account.")
    # Mentions what the key can't do
    assert "```builds, guilds, inventories, pvp, tradingpost, unlocks, wallet```" in sent
    assert syncs == []


async def test_add_another_key():
    stored = {"key": key("B"), "keys": [key("B")]}
    sent, writes, _ = await subject.key_command("add", stored, [(200, TOKEN_INFO), (200, ACCOUNT)], token="A")
    added = key("A", name="Main", permissions=TOKEN_INFO["permissions"])
    # The new key becomes the active one
    assert writes == [(1, "set", {"key": added, "keys": [key("B"), added]})]
    assert sent.startswith("Your key was verified and added to your list of keys")


async def test_add_in_a_server_syncs_roles():
    _, _, syncs = await subject.key_command("add", {}, [(200, TOKEN_INFO), (200, ACCOUNT)], in_guild=True,
                                            token="A")
    assert syncs == ["guildsync", "key role"]


async def test_add_a_known_key():
    stored = {"key": key("A"), "keys": [key("A")]}
    sent, writes, _ = await subject.key_command("add", stored, [(200, TOKEN_INFO), (200, ACCOUNT)], token="A")
    assert sent == "You have already added this key before."
    assert writes == []


async def test_add_beyond_the_limit():
    keys = [key(str(i)) for i in range(15)]
    sent, writes, _ = await subject.key_command("add", {"key": keys[0], "keys": keys},
                                                [(200, TOKEN_INFO), (200, ACCOUNT)], token="A")
    assert sent.startswith("You've reached the maximum limit of 15 API keys")
    assert writes == []


@pytest.mark.parametrize("status, message", [
    (400, "The key is invalid."),
    (503, "The API is currently down. Try again later. "),
])
async def test_add_errors(status, message):
    body = {"text": "Invalid access token"} if status == 400 else {"text": "API not active"}
    sent, writes, _ = await subject.key_command("add", {}, [(status, body)], token="A")
    assert sent == message
    assert writes == []


# --- /key remove -------------------------------------------------------------------------------


async def test_remove_a_key():
    stored = {"key": key("A"), "keys": [key("A"), key("B")]}
    sent, writes, _ = await subject.key_command("remove", stored, token="B")
    assert sent == "Key removed."
    assert writes == [(1, "set", {"key": key("A"), "keys": [key("A")]})]


async def test_remove_an_unknown_key():
    stored = {"key": key("A"), "keys": [key("A")]}
    sent, writes, _ = await subject.key_command("remove", stored, token="Z")
    assert sent == "No keys were removed. Invalid token"
    assert writes == []


# --- /key info, autocomplete --------------------------------------------------------------------


async def test_info():
    stored = {"key": key("A", name="Main"), "keys": [key("A", name="Main"), key("B", account="Alt.5678")]}
    embed, _, _ = await subject.key_command("info", stored)
    assert embed["title"] == "Your keys"
    assert [(f["name"], f["value"]) for f in embed["fields"]] == [
        ("**Active key**: Example.1234 - Main", "Permissions: account, characters\n||A||"),
        ("**1**: Example.1234 - Main", "Permissions: account, characters\n||A||"),
        ("**2**: Alt.5678", "Permissions: account, characters\n||B||"),
    ]


async def test_info_without_keys():
    sent, _, _ = await subject.key_command("info", {})
    assert sent == "You have no keys added, you can add one with /key add."


async def test_key_autocomplete():
    stored = {"key": key("A", name="Main"), "keys": [key("A", name="Main"), key("B", account="Alt.5678", name="x")]}
    assert await subject.key_choices(stored) == [("Example.1234 - Main", "A"), ("Alt.5678 - x", "B")]
    assert await subject.key_choices(stored, "alt") == [("Alt.5678 - x", "B")]


# --- The API key role ---------------------------------------------------------------------------


async def test_key_role_follows_keys():
    role = subject.KEY_ROLE
    members = [subject.server_member(1), subject.server_member(2, role), subject.server_member(3, role),
               subject.server_member(4)]
    users = {1: {"key": key("A")}, 2: {}, 3: {"key": key("C")}}
    changes = await subject.run_key_role_sync(members, users)
    assert changes == {1: [("add", [77])], 2: [("remove", [77])], 3: [], 4: []}


async def test_key_role_sync_skips_servers_it_cant_manage():
    members = [subject.server_member(1)]
    users = {1: {"key": key("A")}}
    assert await subject.run_key_role_sync(members, users, role_exists=False) == {1: []}
    assert await subject.run_key_role_sync(members, users, can_manage_roles=False) == {1: []}
    assert await subject.run_key_role_sync(members, users, settings={"enabled": False, "role": 77}) == {1: []}


# --- Known bugs -----------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="a key saved before the keys list existed can't be removed")
async def test_remove_a_legacy_key():
    sent, writes, _ = await subject.key_command("remove", {"key": key("A")}, token="A")
    assert sent == "Key removed."
    assert writes == [(1, "set", {"key": {}, "keys": []})]


@pytest.mark.xfail(strict=True, reason="removing the active key leaves no active key")
async def test_remove_the_active_key_activates_another():
    stored = {"key": key("A"), "keys": [key("A"), key("B")]}
    sent, writes, _ = await subject.key_command("remove", stored, token="A")
    assert writes == [(1, "set", {"key": key("B"), "keys": [key("B")]})]
    assert sent == "Key removed. Your active key is now Example.1234."
