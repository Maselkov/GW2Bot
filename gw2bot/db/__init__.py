"""MongoDB access."""
from pymongo import ASCENDING, AsyncMongoClient

from .settings import ConfigRepo, SettingsRepo

CONFIG_ID = "GuildWars2"

# Queries that run in loops or lookups over every user or guild
INDEXES = {
    "users": ["key.account_name", "keys.account_name", "event_reminders", "gemtrack"],
    "guilds": [
        "key_sync.enabled",
        "guildsync.enabled",
        "updates.on",
        "news.on",
        "daily.on",
        "bossnotifs.on",
        "force_account_names",
        "link_preview_disabled",
    ],
}


class Data:
    """GW2Bot's database: settings repositories and its other collections."""

    def __init__(self, uri, db_name):
        self.client = AsyncMongoClient(uri)
        self.db = self.client[db_name]
        self.users = SettingsRepo(self.db.users)
        self.guilds = SettingsRepo(self.db.guilds)
        self.channels = SettingsRepo(self.db.channels)
        self.config = ConfigRepo(self.db.config, {"_id": CONFIG_ID})
        # Game data caches, guild syncs, EVTC, ...: the cog's self.db.items,
        # self.db.guildsyncs, self.db.evtc.api_keys, ...
        self.gw2 = self.db
        # Usage counters
        self.statistics = self.db.statistics
        # The bot's own bookkeeping (command sync hash, schema version)
        self.state = self.db.state

    async def ensure_indexes(self):
        for collection, fields in INDEXES.items():
            for field in fields:
                await self.db[collection].create_index([(field, ASCENDING)])

    async def close(self):
        await self.client.close()
