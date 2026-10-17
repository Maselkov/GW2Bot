import asyncio
import copy


class ApiMixin:
    """Calls the GW2 API client (self.api) with a user's stored key."""

    async def call_api(
        self,
        endpoint,
        user=None,
        scopes=None,
        key=None,
        schema_version=None,
        schema_string=None,
    ):
        """GET an endpoint with `key`, or else `user`'s key (checking `scopes`)."""
        if key is None and user:
            key = (await self.fetch_key(user, scopes))["key"]
        data = await self.api.get(endpoint, key=key, schema=schema_version or schema_string)
        if endpoint == "account" and user:
            self.run_in_background(self.check_account_rename(user, key, data))
        return data

    async def call_multiple(
        self, endpoints, user=None, scopes=None, key=None, schema_version=None, schema_string=None
    ):
        """GET several endpoints with one key; results are in input order."""
        if key is None and user:
            key = (await self.fetch_key(user, scopes))["key"]
        return await self.api.get_many(endpoints, key=key, schema=schema_version or schema_string)

    async def check_account_rename(self, user, used_key, account):
        """Update the stored account name if the account was renamed."""
        doc = await self.bot.database.get(user, self)
        key = doc["key"]
        keys = doc["keys"]
        if key["account_name"] == account["name"] or used_key != key["key"]:
            return
        old_name = copy.copy(key["account_name"])
        new_name = account["name"]
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

    def run_in_background(self, coro):
        """Run a coroutine without waiting for it, logging any failure.

        Keeps a reference until it finishes, so the task can't be garbage
        collected mid-run.
        """
        tasks = self.__dict__.setdefault("background_tasks", set())
        task = asyncio.create_task(coro)
        tasks.add(task)

        def done(task):
            tasks.discard(task)
            if not task.cancelled() and task.exception():
                self.log.error("Background task failed", exc_info=task.exception())

        task.add_done_callback(done)
        return task
