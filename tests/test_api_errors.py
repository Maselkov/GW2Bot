"""How GW2 API responses map to results and exceptions."""
import pytest

import subject
from gw2bot.gw2api.errors import (
    APIBadRequest,
    APIConnectionError,
    APIError,
    APIForbidden,
    APIInactiveError,
    APIInvalidKey,
    APINotFound,
    APIRateLimited,
    APIUnavailable,
)

Session = subject.FakeSession


async def test_success_returns_json():
    session = Session((200, {"id": 1}))
    assert await subject.api_get(session, "build") == {"id": 1}
    [(url, _, _)] = session.requests
    assert url == "https://api.guildwars2.com/v2/build"


async def test_partial_content_is_success():
    session = Session((206, [{"id": 1}]))
    assert await subject.api_get(session, "items?ids=1,999999") == [{"id": 1}]


async def test_key_is_sent():
    session = Session((200, {}))
    await subject.api_get(session, "account", key="SECRET")
    [(_, params, _)] = session.requests
    assert params.get("access_token") == "SECRET"


@pytest.mark.parametrize(
    "status, body, error",
    [
        (400, {"text": "invalid key"}, APIInvalidKey),
        (400, {"text": "bad"}, APIBadRequest),
        (403, {"text": "invalid key"}, APIInvalidKey),
        (403, {"text": "requires scope progression"}, APIForbidden),
        (404, {"text": "no such id"}, APINotFound),
        (429, {"text": "too many requests"}, APIRateLimited),
        (503, {"text": "API not active"}, APIInactiveError),
        (503, {"text": "maintenance"}, APIUnavailable),
        (500, {"text": "oops"}, APIConnectionError),
        (502, "<html>Bad Gateway</html>", APIConnectionError),
        (500, {"unexpected": "shape"}, APIConnectionError),
        (401, {"text": "Invalid access token"}, APIInvalidKey),
        (401, "<html>Unauthorized</html>", APIInvalidKey),
        (418, {"text": "teapot"}, APIConnectionError),
    ],
)
async def test_error_statuses(status, body, error):
    session = Session((status, body))
    with pytest.raises(error):
        await subject.api_get(session, "account")


@pytest.mark.parametrize(
    "status, body",
    [
        (400, {"text": "bad"}),
        (400, {"text": "invalid key"}),
        (401, {"text": "Invalid access token"}),
        (403, {"text": "requires scope progression"}),
        (404, {"text": "no such id"}),
        (418, {"text": "teapot"}),
        (503, {"text": "API not active"}),
    ],
)
async def test_client_errors_are_not_retried(status, body):
    session = Session((status, body))
    with pytest.raises(APIError):
        await subject.api_get(session, "account")
    assert len(session.requests) == 1
    assert session.delays == []


@pytest.mark.parametrize(
    "failure",
    [
        (429, {"text": "too many requests"}),
        (500, {"text": "oops"}),
        (502, "<html>Bad Gateway</html>"),
        (503, {"text": "maintenance"}),
        (504, "<html>Gateway Timeout</html>"),
        TimeoutError(),
    ],
    ids=["429", "500", "502", "503", "504", "timeout"],
)
async def test_transient_errors_recover_on_retry(failure):
    session = Session(failure, (200, {"ok": True}))
    assert await subject.api_get(session, "account") == {"ok": True}
    assert len(session.requests) == 2


def test_invalid_key_message():
    from gw2bot.gw2api.errors import APIInvalidKey

    assert subject.api_error_message(APIInvalidKey("Invalid key")) == (
        "Your API key is invalid! Remove your key and add a new one"
    )
