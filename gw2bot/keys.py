"""Users' stored GW2 API keys."""
import asyncio
import copy
import logging

from .gw2api.errors import APIKeyError

log = logging.getLogger(__name__)


class ApiKeys:
    def __init__(self, users):
        # The users SettingsRepo
        self.users = users
        self.background_tasks = set()

    async def get(self, user, scopes=None):
        """The user's active key document ({key, account_name, permissions,
        ...}), checking it has `scopes`. Raises APIKeyError otherwise."""
        doc = await self.users.get(user.id)
        if not doc or "key" not in doc or not doc["key"]:
            raise APIKeyError(
                "No API key associated with your account. "
                "Add your key using `/key add` command. If you don't know "
                "how, the command includes a tutorial.")
        if scopes:
            missing = []
            for scope in scopes:
                if scope not in doc["key"]["permissions"]:
                    missing.append(scope)
            if missing:
                missing = ", ".join(missing)
                raise APIKeyError(
                    "{.mention}, your API key is missing the following "
                    "permissions to use this command: `{}`\nConsider adding "
                    "a new key with those permissions "
                    "checked".format(user, missing))
        return doc["key"]

    def check_account_rename_later(self, user, used_key, account):
        """Check for an account rename in the background (see
        check_account_rename), without delaying the caller."""
        return self.run_in_background(self.check_account_rename(user, used_key, account))

    async def check_account_rename(self, user, used_key, account):
        """Update the stored account name if the account was renamed."""
        doc = await self.users.get(user.id)
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
        await self.users.update(user.id, {"key": key, "keys": keys})
        await user.send(
            "Your account name seems to have "
            "changed! I went ahead and updated it, "
            "from `{}` to `{}`.".format(old_name, new_name)
        )
        await self.users.update(
            user.id,
            {"name_changes": [old_name, new_name]},
            op="push",
        )

    def run_in_background(self, coro):
        """Run a coroutine without waiting for it, logging any failure.

        Keeps a reference until it finishes, so the task can't be garbage
        collected mid-run.
        """
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)

        def done(task):
            self.background_tasks.discard(task)
            if not task.cancelled() and task.exception():
                log.error("Background task failed", exc_info=task.exception())

        task.add_done_callback(done)
        return task
