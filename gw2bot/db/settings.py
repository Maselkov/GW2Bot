"""Settings documents for users, guilds and channels, and the bot's config."""


class SettingsRepo:
    """One document of fields per Discord id (user, guild or channel)."""

    def __init__(self, collection):
        self.collection = collection

    async def get(self, entity_id):
        """The entity's fields (with _id), or {} if it has none."""
        return await self.collection.find_one({"_id": entity_id}) or {}

    async def update(self, entity_id, fields, op="set"):
        """Apply an update operator ("set", "push", "pull", "unset", "inc", ...)
        to the entity's fields, creating the document if needed. Field names
        may use dot notation."""
        op = op if op.startswith("$") else "$" + op
        return await self.collection.update_one({"_id": entity_id}, {op: fields}, upsert=True)

    async def find(self, query=None, *, batch_size=100):
        """Iterate over the fields (with _id) of entities matching `query`."""
        cursor = self.collection.find(query or {})
        if batch_size:
            cursor = cursor.batch_size(batch_size)
        async for doc in cursor:
            yield doc

    async def count(self, query=None):
        return await self.collection.count_documents(query or {})


class ConfigRepo:
    """The bot's single config document (caches, emoji ids, ...)."""

    def __init__(self, collection, selector):
        self.collection = collection
        # How the document is found, e.g. {"_id": "GuildWars2"}
        self.selector = selector

    async def get(self):
        return await self.collection.find_one(self.selector)

    async def update(self, fields, op="set"):
        op = op if op.startswith("$") else "$" + op
        return await self.collection.update_one(self.selector, {op: fields})

    async def ensure_defaults(self, defaults):
        """Create the document from `defaults`, or add any top-level keys it's
        missing. Existing values are kept."""
        doc = await self.get()
        if not doc:
            await self.collection.insert_one({**self.selector, **defaults})
            return
        missing = {k: v for k, v in defaults.items() if k not in doc}
        if missing:
            await self.update(missing)
