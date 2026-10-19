"""/evtc api_key: generating, viewing and revoking upload API keys."""
import re

import subject


def key_in(reply):
    return re.search(r"```(.+?)```", reply).group(1)


async def test_generate_then_view():
    keys = subject.EvtcApiKeys()
    reply = await keys.run("generate")
    assert reply.startswith("Your EVTC API key is:")
    key = key_in(reply)
    assert keys.accepted_tokens() == {key}
    assert key_in(await keys.run("view")) == key


async def test_regenerate_revokes_the_old_key():
    keys = subject.EvtcApiKeys()
    old = key_in(await keys.run("generate"))
    reply = await keys.run("generate")
    assert reply.startswith("Your new EVTC API key is:")
    new = key_in(reply)
    assert new != old
    assert keys.accepted_tokens() == {new}
    assert key_in(await keys.run("view")) == new


async def test_delete_revokes_the_key():
    keys = subject.EvtcApiKeys()
    await keys.run("generate")
    assert await keys.run("delete") == "Your EVTC API key has been deleted."
    assert keys.accepted_tokens() == set()
    assert (await keys.run("view")).startswith("You don't have an EVTC API key generated.")
    assert await keys.run("delete") == "You don't have an EVTC API key generated."


async def test_delete_and_generate_clear_duplicate_keys():
    # Earlier versions left every generated key in place
    keys = subject.EvtcApiKeys()
    await keys.keys.insert_one({"user": 1, "token": "OLD1"})
    await keys.keys.insert_one({"user": 1, "token": "OLD2"})
    new = key_in(await keys.run("generate"))
    assert keys.accepted_tokens() == {new}
    await keys.keys.insert_one({"user": 1, "token": "OLD3"})
    await keys.run("delete")
    assert keys.accepted_tokens() == set()


async def test_keys_are_per_user():
    keys = subject.EvtcApiKeys()
    mine = key_in(await keys.run("generate", user_id=1))
    theirs = key_in(await keys.run("generate", user_id=2))
    await keys.run("generate", user_id=1)
    await keys.run("delete", user_id=1)
    assert keys.accepted_tokens(user_id=1) == set()
    assert keys.accepted_tokens(user_id=2) == {theirs}
    assert mine != theirs
