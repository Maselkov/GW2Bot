import logging

import discord
from discord import app_commands

from ...core.api_client import GW2ApiClient
from ...core.services.account import AccountService
from ...data.repositories import Gw2Repository


class ServiceContainer:
    def __init__(self, bot):
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.api = GW2ApiClient(session=bot.session, logger=self.log)
        # Reuse existing db handle from your current Cog
        self.repo = Gw2Repository(bot.database.db.gw2)
        # utilities shim; you can inject specific helpers if needed
        self.utils = {}
        self._account_service = None

    @property
    def account_service(self) -> AccountService:
        if not self._account_service:
            self._account_service = AccountService(self.api, self.repo, self.utils)
        return self._account_service


class GuildWars2(discord.ext.commands.Cog):
    """Facade Cog composed of services.

    For incremental migration: keep the name and setup signature identical
    to your existing extension entry point if you want to swap it in later.
    """

    def __init__(self, bot):
        self.bot = bot
        self.container = ServiceContainer(bot)
        self.embed_color = 0xC12D2B

    async def get_embed_color(self, interaction: discord.Interaction) -> int:
        if not hasattr(interaction, "user"):
            return self.embed_color
        doc = await self.bot.database.users.find_one(
            {"_id": interaction.user.id}, {"embed_color": 1, "_id": 0}
        )
        if doc and doc.get("embed_color"):
            return int(doc["embed_color"], 16)
        return self.embed_color
