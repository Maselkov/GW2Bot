from .exceptions import (APIBadRequest, APIConnectionError, APIError,
                         APIForbidden, APINotFound)


class ApiMixin:
    async def get_world_id(self, world):
        if world is None:
            return None
        try:
            results = await self.call_api("worlds?ids=all")
        except APIError:
            return None
        for w in results:
            if w["name"].lower() == world.lower():
                return w["id"]
        return None

    async def get_guild(self, gid):
        endpoint = "guild/{0}".format(gid)
        try:
            results = await self.call_api(endpoint)
        except APIError:
            return None
        return results

    async def call_multiple(self, endpoints, user=None, scopes=None, key=None):
        if key is None and user:
            doc = await self.fetch_key(user, scopes)
            key = doc["key"]
        res = []
        for e in endpoints:
            res.append(await self.call_api(e, key=key))
        return res

    async def call_api(self, endpoint, user=None, scopes=None, key=None):
        headers = {
            'User-Agent': "GW2Bot - a Discord bot",
            'Accept': 'application/json'
        }
        if key:
            headers.update({"Authorization": "Bearer " + key})
        if user:
            doc = await self.fetch_key(user, scopes)
            headers.update({"Authorization": "Bearer " + doc["key"]})
        apiserv = 'https://api.guildwars2.com/v2/'
        url = apiserv + endpoint
        async with self.session.get(url, headers=headers) as r:
            if r.status != 200 and r.status != 206:
                if r.status == 400:
                    raise APIBadRequest("Bad request")
                if r.status == 404:
                    raise APINotFound("Not found")
                if r.status == 403:
                    raise APIForbidden("Access denied")
                if r.status == 429:
                    self.log.error("API Call limit saturated")
                    raise APIConnectionError(
                        "Requests limit has been saturated. Try again later.")
                else:
                    raise APIConnectionError(str(r.status))
            results = await r.json()
        return results
