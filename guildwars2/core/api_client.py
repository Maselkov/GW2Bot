import asyncio
from typing import Any, Iterable, Optional

try:
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_chain,
        wait_fixed,
    )
except Exception:  # pragma: no cover - provide no-op fallbacks

    def retry(*args, **kwargs):
        def _decorator(func):
            return func

        return _decorator

    def retry_if_exception_type(*args, **kwargs):
        return None

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_chain(*args, **kwargs):
        return None

    def wait_fixed(*args, **kwargs):
        return None


from ..exceptions import (
    APIBadRequest,
    APIConnectionError,
    APIForbidden,
    APIInactiveError,
    APIInvalidKey,
    APINotFound,
    APIRateLimited,
    APIUnavailable,
)


class GW2ApiClient:
    """Thin async client over the GW2 REST API.

    This lifts logic out of the mixin and makes it reusable by services.
    """

    def __init__(self, session, logger):
        self.session = session
        self.log = logger

    async def get_many(
        self,
        endpoints: Iterable[str],
        *,
        user=None,
        scopes=None,
        key: Optional[str] = None,
        **kwargs,
    ):
        if key is None and user:
            # delegate to caller to supply key; services can fetch via repository
            # kept for compatibility if a user is passed
            pass
        tasks = [
            self.get(e, user=user, scopes=scopes, key=key, **kwargs) for e in endpoints
        ]
        return await asyncio.gather(*tasks)

    async def _post_fetch_hook(
        self, endpoint: str, data: Any, used_key: Optional[str], user
    ):
        # Services can override/extend via composition; for now, no-op.
        return

    @retry(
        retry=retry_if_exception_type(APIBadRequest),
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_chain(wait_fixed(2), wait_fixed(4), wait_fixed(8)),
    )
    async def get(
        self,
        endpoint: str,
        *,
        user=None,
        scopes=None,
        key: Optional[str] = None,
        schema_version=None,
        schema_string: Optional[str] = None,
    ) -> Any:
        headers = {"User-Agent": "GW2Bot - a Discord bot", "Accept": "application/json"}
        params = []
        use_headers = False
        if key:
            if use_headers:
                headers.update({"Authorization": "Bearer " + key})
            else:
                params.append(("access_token", key))
        # Caller can embed schema versions
        if schema_version:
            schema = schema_version.replace(microsecond=0).isoformat() + "Z"
            headers.update({"X-Schema-Version": schema})
        if schema_string:
            headers.update({"X-Schema-Version": schema_string})
        apiserv = "https://api.guildwars2.com/v2/"
        url = apiserv + endpoint
        async with self.session.get(url, headers=headers, params=params) as r:
            if r.status not in (200, 206):
                try:
                    err = await r.json()
                    err_msg = err.get("text", "")
                except Exception:
                    err_msg = ""
                if r.status == 400:
                    if err_msg == "invalid key":
                        raise APIInvalidKey("Invalid key")
                    raise APIBadRequest("Bad request")
                if r.status == 404:
                    raise APINotFound("Not found")
                if r.status == 403:
                    if err_msg == "invalid key":
                        raise APIInvalidKey("Invalid key")
                    raise APIForbidden("Access denied")
                if r.status == 503 and err_msg == "API not active":
                    raise APIInactiveError("API is dead")
                if r.status == 429:
                    self.log.error("API Call limit saturated")
                    raise APIRateLimited(
                        "Requests limit has been saturated. Try again later."
                    )
                if r.status == 503:
                    raise APIUnavailable("ArenaNet has disabled the API.")
                else:
                    raise APIConnectionError(f"{r.status} {err_msg}")
            data = await r.json()
            asyncio.create_task(self._post_fetch_hook(endpoint, data, key, user))
            return data
