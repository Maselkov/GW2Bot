"""The GW2 API client: retries, headers, concurrency, and the cog's use of it."""
import datetime
import json
import traceback

import aiohttp
import pytest

import subject
from conftest import ROOT
from gw2bot.gw2api.errors import (
    APIConnectionError,
    APIRateLimited,
    APIUnavailable,
)

Session = subject.FakeSession
FIXTURES = ROOT / "tests" / "fixtures" / "gw2api"


# --- Retries ---------------------------------------------------------------


async def test_gives_up_after_three_attempts():
    session = Session((429, {"text": "too many requests"}))
    with pytest.raises(APIRateLimited):
        await subject.api_get(session, "account")
    assert len(session.requests) == 3
    assert len(session.delays) == 2


async def test_backoff_grows_with_jitter():
    session = Session((500, {"text": "oops"}))
    with pytest.raises(APIConnectionError):
        await subject.api_get(session, "account")
    first, second = session.delays
    assert 0.5 <= first <= 0.75
    assert 1.0 <= second <= 1.5


async def test_retry_after_is_honoured_and_capped():
    session = Session(
        (429, {"text": "slow down"}, {"Retry-After": "2"}),
        (503, {"text": "maintenance"}, {"Retry-After": "120"}),
        (200, {"ok": True}),
    )
    assert await subject.api_get(session, "account") == {"ok": True}
    assert session.delays == [2.0, 5.0]


async def test_unparseable_retry_after_falls_back_to_backoff():
    session = Session((503, {"text": "maintenance"}, {"Retry-After": "soon"}), (200, {}))
    await subject.api_get(session, "account")
    [delay] = session.delays
    assert 0.5 <= delay <= 0.75


@pytest.mark.parametrize(
    "failure",
    [TimeoutError(), aiohttp.ClientConnectionError("connection reset")],
    ids=["timeout", "connection"],
)
async def test_network_failures_become_api_errors(failure):
    session = Session(failure)
    with pytest.raises(APIConnectionError):
        await subject.api_get(session, "account")
    assert len(session.requests) == 3


async def test_errors_never_include_the_key():
    secret = "SECRET-KEY"
    failure = aiohttp.ClientConnectionError(f"failed for ?access_token={secret}")
    for responses in [(failure,), ((500, {"text": "oops"}),), ((429, {"text": "x"}),)]:
        with pytest.raises(Exception) as caught:
            await subject.api_get(Session(*responses), "account", key=secret)
        # Includes chained exceptions, as a logged traceback would
        assert secret not in "".join(traceback.format_exception(caught.value))


async def test_retries_are_logged_without_the_key(caplog):
    session = Session((503, {"text": "maintenance"}), (200, {}))
    with caplog.at_level("WARNING", logger="gw2bot.gw2api.client"):
        await subject.api_get(session, "account/wallet?ids=1", key="SECRET-KEY")
    [record] = caplog.records
    assert "account/wallet" in record.getMessage()
    assert "SECRET" not in record.getMessage()
    assert "ids=" not in record.getMessage()


async def test_unavailable_is_raised_once_retries_run_out():
    session = Session((503, {"text": "maintenance"}))
    with pytest.raises(APIUnavailable):
        await subject.api_get(session, "account")


# --- Requests --------------------------------------------------------------


async def test_headers():
    session = Session((200, {}))
    await subject.api_get(session, "account")
    [(_, params, headers)] = session.requests
    assert headers["User-Agent"] == "GW2Bot - a Discord bot"
    assert headers["Accept"] == "application/json"
    assert "X-Schema-Version" not in headers
    assert "Authorization" not in headers
    assert params == {}


@pytest.mark.parametrize(
    "schema, expected",
    [
        (datetime.datetime(2019, 2, 21), "2019-02-21T00:00:00Z"),
        (datetime.datetime(2019, 2, 21, 13, 5, 9, 123456), "2019-02-21T13:05:09Z"),
        ("2021-07-15T13:00:00.000Z", "2021-07-15T13:00:00.000Z"),
    ],
)
async def test_schema_version(schema, expected):
    session = Session((200, {}))
    await subject.api_get(session, "account", schema=schema)
    [(_, _, headers)] = session.requests
    assert headers["X-Schema-Version"] == expected


async def test_get_many_keeps_order_and_limits_concurrency():
    session = Session(*[(200, {"n": i}) for i in range(25)])
    endpoints = [f"items/{i}" for i in range(25)]
    results = await subject.api_get_many(session, endpoints, key="KEY")
    assert len(results) == 25
    assert session.max_in_flight == 10
    assert all(params == {"access_token": "KEY"} for _, params, _ in session.requests)


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
async def test_recorded_responses_pass_through(path):
    recorded = json.loads(path.read_text(encoding="utf-8"))
    assert await subject.api_get(Session((200, recorded)), "x") == recorded


# --- The cog's use of the client --------------------------------------------


def stored_account(name="Example.1234", key="KEY"):
    return {
        "key": {"key": key, "account_name": name, "permissions": ["account"]},
        "keys": [
            {"key": key, "account_name": name},
            {"key": "OTHER", "account_name": "Alt.5678"},
        ],
    }


def account_fixture():
    """A synthetic /v2/account response (never commit real account data)."""
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        "name": "Example.1234",
        "age": 1000000,
        "world": 2001,
        "guilds": [],
        "created": "2015-01-01T00:00:00Z",
        "access": ["GuildWars2", "HeartOfThorns", "PathOfFire"],
        "commander": False,
    }


async def test_account_lookup_uses_the_stored_key():
    session = Session((200, account_fixture()))
    data, writes, sent = await subject.fetch_account(session, stored_account())
    assert data["name"] == "Example.1234"
    [(_, params, _)] = session.requests
    assert params == {"access_token": "KEY"}
    assert writes == [] and sent == []


async def test_account_rename_is_recorded_and_announced():
    session = Session((200, account_fixture()))
    data, writes, sent = await subject.fetch_account(session, stored_account(name="Old.1111"))
    assert writes[0] == ("set", {
        "key": {"key": "KEY", "account_name": "Example.1234", "permissions": ["account"]},
        "keys": [
            {"key": "KEY", "account_name": "Example.1234"},
            {"key": "OTHER", "account_name": "Alt.5678"},
        ],
    })
    assert writes[1] == ("push", {"name_changes": ["Old.1111", "Example.1234"]})
    [message] = sent
    assert "from `Old.1111` to `Example.1234`" in message


async def test_rename_check_failures_are_logged_not_raised(caplog):
    stored = stored_account(name="Old.1111")
    del stored["keys"]
    session = Session((200, account_fixture()))
    with caplog.at_level("ERROR", logger="tests"):
        data, writes, sent = await subject.fetch_account(session, stored)
    assert data["name"] == "Example.1234"
    assert any("Background task failed" in r.getMessage() for r in caplog.records)
