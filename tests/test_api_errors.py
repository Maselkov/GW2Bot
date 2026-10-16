"""How GW2 API responses map to results and exceptions."""
import pytest

import subject
from cogs.guildwars2.exceptions import (
    APIBadRequest,
    APIConnectionError,
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
    [(url, _)] = session.requests
    assert url == "https://api.guildwars2.com/v2/build"


async def test_partial_content_is_success():
    session = Session((206, [{"id": 1}]))
    assert await subject.api_get(session, "items?ids=1,999999") == [{"id": 1}]


async def test_key_is_sent():
    session = Session((200, {}))
    await subject.api_get(session, "account", key="SECRET")
    [(_, params)] = session.requests
    assert params.get("access_token") == "SECRET"


@pytest.mark.parametrize(
    "status, body, error",
    [
        (400, {"text": "invalid key"}, APIInvalidKey),
        (403, {"text": "invalid key"}, APIInvalidKey),
        (403, {"text": "requires scope progression"}, APIForbidden),
        (404, {"text": "no such id"}, APINotFound),
        (429, {"text": "too many requests"}, APIRateLimited),
        (503, {"text": "API not active"}, APIInactiveError),
        (503, {"text": "maintenance"}, APIUnavailable),
        (500, {"text": "oops"}, APIConnectionError),
        (502, "<html>Bad Gateway</html>", APIConnectionError),
        (500, {"unexpected": "shape"}, APIConnectionError),
    ],
)
async def test_error_statuses(status, body, error):
    session = Session((status, body))
    with pytest.raises(error):
        await subject.api_get(session, "account")
    assert len(session.requests) == 1


async def test_bad_request_is_retried_then_raised():
    session = Session((400, {"text": "bad"}))
    with pytest.raises(APIBadRequest):
        await subject.api_get(session, "account")
    assert len(session.requests) == 4


async def test_bad_request_recovers_on_retry():
    session = Session((400, {"text": "bad"}), (200, {"ok": True}))
    assert await subject.api_get(session, "account") == {"ok": True}
    assert len(session.requests) == 2
