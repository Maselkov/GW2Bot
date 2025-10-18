from typing import Any, Iterable, Optional

from ...exceptions import APIKeyError


class KeyService:
    """Centralized API key retrieval and scope validation.

    Transitional: uses the bot.database handle until a dedicated repository exists.
    """

    def __init__(self, bot_database):
        self._db = bot_database

    async def get_key_for_user(
        self,
        user: Any,
        *,
        required_scopes: Optional[Iterable[str]] = None,
        cog: Any = None,
    ) -> dict:
        """Return the stored key document for the user or raise APIKeyError.

        Returns the full key document (containing 'key', 'permissions',
        'account_name', etc.).
        """
        doc = await self._db.get_user(user, cog)
        if not doc or "key" not in doc or not doc["key"]:
            raise APIKeyError(
                "No API key associated with your account. "
                "Add your key using `/key add` command. If you don't know "
                "how, the command includes a tutorial."
            )
        if required_scopes:
            missing = [
                s for s in required_scopes if s not in doc["key"].get("permissions", [])
            ]
            if missing:
                missing_str = ", ".join(missing)
                # Keep message semantics similar to existing behavior
                raise APIKeyError(
                    f"{user.mention}, your API key is missing the following "
                    f"permissions to use this command: `{missing_str}`\n"
                    "Consider adding a new key with those permissions checked"
                )
        return doc["key"]
