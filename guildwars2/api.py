import asyncio
from aiohttp import ContentTypeError
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_chain, wait_fixed)

from .exceptions import (APIBadRequest, APIConnectionError, APIForbidden,
                         APIInactiveError, APIInvalidKey, APINotFound,
                         APIRateLimited)
import json


class ApiMixin:

    async def call_multiple(self,
                            endpoints,
                            user=None,
                            scopes=None,
                            key=None,
                            **kwargs):
        if key is None and user:
            doc = await self.fetch_key(user, scopes)
            key = doc["key"]
        tasks = []
        for e in endpoints:
            tasks.append(self.call_api(e, key=key, **kwargs))
        return await asyncio.gather(*tasks)

    async def cache_result(self, endpoint, key, user):
        pass

    @retry(retry=retry_if_exception_type(APIBadRequest),
           reraise=True,
           stop=stop_after_attempt(4),
           wait=wait_chain(wait_fixed(2), wait_fixed(4), wait_fixed(8)))
    async def call_api(self,
                       endpoint,
                       user=None,
                       scopes=None,
                       key=None,
                       schema_version=None,
                       schema_string=None):
        headers = {
            'User-Agent': "GW2Bot - a Discord bot",
            'Accept': 'application/json'
        }
        if key:
            headers.update({"Authorization": "Bearer " + key})
        if user:
            doc = await self.fetch_key(user, scopes)
            headers.update({"Authorization": "Bearer " + doc["key"]})
        if schema_version:
            schema = schema_version.replace(microsecond=0).isoformat() + "Z"
            headers.update({"X-Schema-Version": schema})
        if schema_string:
            headers.update({"X-Schema-Version": schema_string})
        apiserv = 'https://api.guildwars2.com/v2/'
        url = apiserv + endpoint
        async with self.session.get(url, headers=headers) as r:
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
                        "Requests limit has been saturated. Try again later.")
                else:
                    raise APIConnectionError("{} {}".format(r.status, err_msg))
            data = await r.json()
            asyncio.create_task(self.cache_result(endpoint, key, user))
            return data
