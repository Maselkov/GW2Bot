"""MongoDB access."""
from pymongo import AsyncMongoClient

from .settings import ConfigRepo, SettingsRepo

# Settings are still stored the Toothy way: a subdocument named after the
# cog in shared users/guilds/channels documents, and a configs document
# keyed by cog name
COG_NAME = "GuildWars2"


class Data:
    """The bot's data: settings repositories and the gw2.* collections."""

    def __init__(self, uri, db_name):
        self.client = AsyncMongoClient(uri)
        self.db = self.client[db_name]
        prefix = f"cogs.{COG_NAME}"
        self.users = SettingsRepo(self.db.users, prefix)
        self.guilds = SettingsRepo(self.db.guilds, prefix)
        self.channels = SettingsRepo(self.db.channels, prefix)
        self.config = ConfigRepo(self.db.configs, {"cog_name": COG_NAME})
        # Game data caches, guild syncs, EVTC, ... (gw2.items, gw2.guildsyncs, ...)
        self.gw2 = self.db.gw2
        # The bot's own bookkeeping (command sync hash)
        self.state = self.db.gw2bot_state

    async def close(self):
        await self.client.close()
