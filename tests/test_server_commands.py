"""/server api_key_role, /key switch and the guild sync limit."""
import subject

# --- /server api_key_role -------------------------------------------------------------


async def test_api_key_role_enable():
    from unittest.mock import MagicMock

    sent, writes, synced = await subject.api_key_role(enabled=True, role=MagicMock(id=77))
    assert sent == "Key sync enabled. Members with valid API keys will now be given the selected role"
    assert writes == [(10, "set", {"key_sync.enabled": True, "key_sync.role": 77})]
    assert synced


async def test_api_key_role_enable_needs_a_role():
    sent, writes, _ = await subject.api_key_role(enabled=True)
    assert sent == "If enabling, you must specify a role to give to members with an API key."
    assert writes == []


async def test_api_key_role_disable_without_a_role():
    sent, writes, synced = await subject.api_key_role(enabled=False)
    assert sent == "Key sync disabled."
    # The role is kept for when it's enabled again
    assert writes == [(10, "set", {"key_sync.enabled": False})]
    assert not synced


# --- /key switch ------------------------------------------------------------------------


def key(token, name=""):
    return {"key": token, "account_name": "Example.1234", "name": name, "permissions": ["account"]}


async def test_switch_key_names_the_new_key():
    stored = {"key": key("A"), "keys": [key("A"), key("B", "Alt")]}
    sent, writes = await subject.switch_key(stored, "B")
    assert sent == "Swapped to selected key. Name : `Alt`"
    assert writes == [(1, "set", {"key": key("B", "Alt")})]


async def test_switch_to_an_unnamed_key():
    stored = {"key": key("A", "Main"), "keys": [key("A", "Main"), key("B")]}
    sent, _ = await subject.switch_key(stored, "B")
    assert sent == "Swapped to selected key."


async def test_switch_without_an_active_key():
    # E.g. after removing the active key
    stored = {"key": {}, "keys": [key("A"), key("B", "Alt")]}
    sent, writes = await subject.switch_key(stored, "B")
    assert sent == "Swapped to selected key. Name : `Alt`"
    assert writes == [(1, "set", {"key": key("B", "Alt")})]


async def test_switch_to_the_active_or_an_unknown_key():
    stored = {"key": key("A"), "keys": [key("A"), key("B")]}
    assert (await subject.switch_key(stored, "A"))[0] == "That key is currently active."
    assert (await subject.switch_key(stored, "C"))[0] == "That key is not in your account."


# --- Guild sync limit ----------------------------------------------------------------------


async def test_guildsync_limit_is_eight():
    assert await subject.can_add_guildsync([f"G{i}" for i in range(7)])
    assert not await subject.can_add_guildsync([f"G{i}" for i in range(8)])


async def test_guildsync_for_an_already_synced_guild():
    assert not await subject.can_add_guildsync(["G0"], "G0")
