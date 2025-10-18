from typing import Any, Dict


class AccountService:
    """Discord-free account logic.

    The Cog should call into this and render embeds.
    """

    def __init__(self, api_client, repo, utils):
        self.api = api_client
        self.repo = repo
        self.utils = utils

    async def get_account(self, *, key: str) -> Dict[str, Any]:
        return await self.api.get("account", key=key)

    async def get_pvp_stats(self, *, key: str) -> Dict[str, Any]:
        return await self.api.get("pvp/stats", key=key)

    async def get_achievements(self, *, key: str):
        return await self.api.get("account/achievements", key=key)
