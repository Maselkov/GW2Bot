from .exceptions import (APIBadRequest, APIConnectionError, APIError,
                         APIForbidden, APIInvalidKey, APINotFound,
                         APIInactiveError)


class ApiMixin:
    async def get_guild(self, ctx, guild_id=None, guild_name=None):
        if guild_name:
            endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
        elif not guild_id:
            if not ctx.guild:
                return None
            doc = await self.bot.database.get_guild(ctx.guild, self) or {}
            guild_id = doc.get("guild_ingame")
        if not guild_id:
            return None
        endpoint = "guild/{0}".format(guild_id)
        return await self.call_api(endpoint, ctx.author, ["guilds"])

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
                try:
                    err = await r.json()
                    err_msg = err["text"]
                except:
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
                    raise APIConnectionError(
                        "Requests limit has been saturated. Try again later.")
                else:
                    raise APIConnectionError("{} {}".format(r.status, err_msg))
            return await r.json()
