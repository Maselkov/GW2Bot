import asyncio
from aiohttp import ContentTypeError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_chain,
    wait_fixed,
)
import copy
from .exceptions import (
    APIBadRequest,
    APIConnectionError,
    APIForbidden,
    APIInactiveError,
    APIInvalidKey,
    APINotFound,
    APIRateLimited,
    APIUnavailable,
)
import json


class ApiMixin:
    async def call_multiple(
        self, endpoints, user=None, scopes=None, key=None, **kwargs
    ):
        if key is None and user:
            doc = await self.fetch_key(user, scopes)
            key = doc["key"]
        tasks = []
        for e in endpoints:
            tasks.append(self.call_api(e, key=key, **kwargs))
        return await asyncio.gather(*tasks)

    async def cache_result(self, endpoint, result, used_key, user):
        if endpoint == "account" and user:
            doc = await self.bot.database.get(user, self)
            key = doc["key"]
            keys = doc["keys"]
            if key["account_name"] != result["name"]:
                if used_key == key["key"]:
                    old_name = copy.copy(key["account_name"])
                    new_name = result["name"]
                    key["account_name"] = new_name
                    for alt_key in keys:
                        if alt_key["account_name"] == old_name:
                            alt_key["account_name"] = new_name
                    await self.bot.database.set(user, {"key": key, "keys": keys}, self)
                    await user.send(
                        "Your account name seems to have "
                        "changed! I went ahead and updated it, "
                        "from `{}` to `{}`.".format(old_name, new_name)
                    )
                    await self.bot.database.set(
                        user,
                        {"name_changes": [old_name, new_name]},
                        self,
                        operator="push",
                    )

    @retry(
        retry=retry_if_exception_type(APIBadRequest),
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_chain(wait_fixed(2), wait_fixed(4), wait_fixed(8)),
    )
    async def call_api(
        self,
        endpoint,
        user=None,
        scopes=None,
        key=None,
        schema_version=None,
        schema_string=None,
    ):
        headers = {"User-Agent": "GW2Bot - a Discord bot", "Accept": "application/json"}
        params = []
        use_headers = False
        if key:
            if use_headers:
                headers.update({"Authorization": "Bearer " + key})
            else:
                params.append(("access_token", key))
        if user:
            doc = await self.fetch_key(user, scopes)
            key = doc["key"]
            if use_headers:
                headers.update({"Authorization": "Bearer " + key})
            else:
                params.append(("access_token", key))
        if schema_version:
            schema = schema_version.replace(microsecond=0).isoformat() + "Z"
            headers.update({"X-Schema-Version": schema})
        if schema_string:
            headers.update({"X-Schema-Version": schema_string})
        apiserv = "https://api.guildwars2.com/v2/"
        url = apiserv + endpoint
        async with self.session.get(url, headers=headers, params=params) as r:
            if r.status != 200 and r.status != 206:
                try:
                    err = await r.json()
                    err_msg = err["text"]
                except (json.JSONDecodeError, KeyError, ContentTypeError):
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
                    raise APIConnectionError("{} {}".format(r.status, err_msg))
            data = await r.json()
            asyncio.create_task(self.cache_result(endpoint, data, key, user))
            return data
