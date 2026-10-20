"""The GW2 API and the other websites the bot reads."""
import asyncio
from unittest.mock import MagicMock


class AsyncContext:
    """`async with` for a ready value."""

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


class FakeResponse:
    def __init__(self, session, status, body, headers):
        self.session = session
        self.status = status
        self._body = body
        self.headers = headers

    async def json(self):
        import aiohttp

        if isinstance(self._body, str):
            raise aiohttp.ContentTypeError(MagicMock(), ())
        return self._body

    async def __aenter__(self):
        self.session.in_flight += 1
        self.session.max_in_flight = max(self.session.max_in_flight, self.session.in_flight)
        # Let other requests start, so concurrency limits are observable
        for _ in range(3):
            await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc):
        self.session.in_flight -= 1
        return False


class FakeFailure:
    """Raised when the request is made: a timeout or network error."""

    def __init__(self, error):
        self.error = error

    async def __aenter__(self):
        raise self.error

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Serves queued responses to the GW2 API client.

    Each response is (status, body), (status, body, headers) or an
    exception to raise; a str body is a non-JSON page. The last response
    repeats once the queue is exhausted. Records requests as (url, query
    params, headers) and retry waits in `delays`.

    HEAD requests (the bot checking a wiki page exists) are 200 for the
    URLs in `pages`, else 404, and recorded in `heads`; `head_error` (an
    exception) makes them all fail.
    """

    def __init__(self, *responses, pages=(), head_error=None):
        self.responses = list(responses)
        self.pages = set(pages)
        self.head_error = head_error
        self.heads = []
        self.requests = []
        self.delays = []
        self.in_flight = 0
        self.max_in_flight = 0

    def get(self, url, headers=None, params=None, timeout=None):
        self.requests.append((url, dict(params or []), dict(headers or {})))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, BaseException):
            return FakeFailure(response)
        status, body, *rest = response
        return FakeResponse(self, status, body, rest[0] if rest else {})

    def head(self, url, **kwargs):
        self.heads.append(url)
        if self.head_error:
            return FakeFailure(self.head_error)
        return FakeResponse(self, 200 if url in self.pages else 404, None, {})


class FakeImageSession:
    """Serves {url: image bytes}; any other URL is a 404. Records requests."""

    def __init__(self, images):
        self.images = images
        self.requests = []

    def get(self, url, timeout=None):
        self.requests.append(url)
        return _ImageResponse(self.images.get(url))


class _ImageResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        if self.body is None:
            import aiohttp

            raise aiohttp.ClientResponseError(MagicMock(), (), status=404)

    async def read(self):
        return self.body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePageSession:
    """Serves {url: (status, text)}; anything else is a 404."""

    def __init__(self, pages):
        self.pages = pages

    def get(self, url, timeout=None):
        status, text = self.pages.get(url, (404, "Not found"))
        response = MagicMock(status=status)

        async def read_text():
            return text

        response.text = read_text
        return AsyncContext(response)


class FakeWikiSession:
    """Serves pages, {url: text}; `redirects` maps a search URL to the page
    it lands on (an exact match). Records (url, headers)."""

    def __init__(self, pages=None, redirects=None):
        self.pages = pages or {}
        self.redirects = redirects or {}
        self.requests = []

    def get(self, url, headers=None, **kwargs):
        self.requests.append((url, dict(headers or {})))
        target = self.redirects.get(url)
        response = MagicMock(history=[MagicMock()] if target else [], url=target or url)

        async def text():
            return self.pages[target or url]

        response.text = text
        return AsyncContext(response)


class FakeDpsReport:
    """dps.report: getUserToken gives `token`; uploadContent answers
    `upload` (an error, or a report whose id getJson serves from
    `reports`). Records requests as (method, url, params)."""

    def __init__(self, reports=None, *, upload=None, token="DPS-TOKEN"):
        self.reports = reports or {}
        self.upload = upload
        self.token = token
        self.requests = []

    def _response(self, body):
        response = MagicMock()

        async def json():
            return body

        response.json = json
        return AsyncContext(response)

    def get(self, url, params=None, **kwargs):
        self.requests.append(("GET", url, dict(params or {})))
        if url.endswith("getUserToken"):
            return self._response({"userToken": self.token})
        return self._response(self.reports[params["id"]])

    def post(self, url, data=None, params=None, **kwargs):
        self.requests.append(("POST", url, dict(params or {})))
        return self._response(self.upload)
