"""Client for the Guild Wars 2 API (https://api.guildwars2.com/v2/)."""
import asyncio
import datetime
import json
import logging
import random

import aiohttp

from .errors import (
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

log = logging.getLogger(__name__)

BASE_URL = "https://api.guildwars2.com/v2/"
USER_AGENT = "GW2Bot - a Discord bot"
# Upper bound on how long a Retry-After header can make us wait
MAX_RETRY_AFTER = 5.0


class Client:
    """Makes GW2 API requests, mapping failures to APIError subclasses.

    Rate limits (429), server errors (5xx, except a disabled endpoint),
    timeouts and network errors are retried with exponential backoff; other
    errors are raised straight away.
    """

    def __init__(
        self,
        session,
        *,
        timeout=15,
        attempts=3,
        backoff=0.5,
        concurrency=10,
        sleep=asyncio.sleep,
    ):
        self.session = session
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.attempts = attempts
        self.backoff = backoff
        self.concurrency = concurrency
        self.sleep = sleep

    async def get(self, endpoint, *, key=None, schema=None):
        """GET an endpoint (relative to /v2/, may include a query string).

        key: API key sent as access_token. schema: X-Schema-Version, as a
        datetime or a string.
        """
        for attempt in range(1, self.attempts + 1):
            try:
                return await self._get_once(endpoint, key, schema)
            except APIError as error:
                if not error.retryable or attempt == self.attempts:
                    raise
                delay = self.retry_delay(attempt, error)
                log.warning(
                    "GW2 API %s failed (%s), retrying in %.1fs",
                    endpoint.split("?")[0],
                    type(error).__name__,
                    delay,
                )
                await self.sleep(delay)

    async def get_many(self, endpoints, *, key=None, schema=None):
        """GET several endpoints concurrently; results are in input order."""
        semaphore = asyncio.Semaphore(self.concurrency)

        async def get(endpoint):
            async with semaphore:
                return await self.get(endpoint, key=key, schema=schema)

        return await asyncio.gather(*(get(e) for e in endpoints))

    def retry_delay(self, attempt, error):
        if error.retry_after is not None:
            return min(error.retry_after, MAX_RETRY_AFTER)
        delay = self.backoff * 2 ** (attempt - 1)
        return delay + random.uniform(0, delay / 2)

    async def _get_once(self, endpoint, key, schema):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if schema:
            if isinstance(schema, datetime.datetime):
                schema = schema.replace(microsecond=0).isoformat() + "Z"
            headers["X-Schema-Version"] = schema
        # The key goes in the query string: the API has rejected requests
        # with an Authorization: Bearer header (see commit e52fb49)
        params = [("access_token", key)] if key else []
        try:
            async with self.session.get(
                BASE_URL + endpoint, headers=headers, params=params, timeout=self.timeout
            ) as response:
                if response.status not in (200, 206):
                    raise await error_for(response)
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            # Not chained: aiohttp errors include the URL, and with it the key
            raise APIConnectionError(f"Could not reach the API ({type(e).__name__})") from None


async def error_for(response):
    """The APIError for a failed response."""
    try:
        text = (await response.json())["text"]
    except (json.JSONDecodeError, KeyError, TypeError, aiohttp.ContentTypeError):
        text = ""
    status = response.status
    if status == 400:
        if text == "invalid key":
            return APIInvalidKey("Invalid key")
        return APIBadRequest("Bad request")
    if status == 401:
        # What the API returns for an unknown or deleted key
        return APIInvalidKey("Invalid key")
    if status == 404:
        return APINotFound("Not found")
    if status == 403:
        if text == "invalid key":
            return APIInvalidKey("Invalid key")
        return APIForbidden("Access denied")
    if status == 503 and text == "API not active":
        return APIInactiveError("API is dead")
    if status == 429:
        log.error("API Call limit saturated")
        return APIRateLimited(
            "Requests limit has been saturated. Try again later.",
            retry_after=retry_after(response),
        )
    if status == 503:
        return APIUnavailable("ArenaNet has disabled the API.", retry_after=retry_after(response))
    error = APIConnectionError("{} {}".format(status, text))
    # Other 4xx won't change on a retry
    error.retryable = status >= 500
    return error


def retry_after(response):
    try:
        return max(0.0, float(response.headers.get("Retry-After", "")))
    except ValueError:
        return None
