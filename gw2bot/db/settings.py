"""Settings documents for users, guilds and channels, and the bot's config.

Callers work with a document of fields per Discord id and never need to know
where it's stored: today a `cogs.GuildWars2` subdocument in Toothy's shared
collections (prefix "cogs.GuildWars2"), later a collection of its own
(prefix "").
"""

LOGICAL_OPERATORS = ("$and", "$or", "$nor")


class SettingsRepo:
    def __init__(self, collection, prefix=""):
        self.collection = collection
        self.prefix = prefix

    def _field(self, name):
        return f"{self.prefix}.{name}" if self.prefix else name

    def _query(self, query):
        """Make a query on the entity's fields address where they're stored."""
        result = {}
        for key, value in query.items():
            if key in LOGICAL_OPERATORS:
                result[key] = [self._query(q) for q in value]
            elif key == "_id" or key.startswith("$"):
                result[key] = value
            else:
                result[self._field(key)] = value
        return result

    def _projection(self):
        return {self.prefix: 1} if self.prefix else None

    def _fields(self, doc):
        """The entity's fields from a stored document, with its _id, or None."""
        if doc is None:
            return None
        fields = doc
        if self.prefix:
            for part in self.prefix.split("."):
                fields = fields.get(part) if isinstance(fields, dict) else None
                if fields is None:
                    return None
        result = dict(fields)
        result["_id"] = doc["_id"]
        return result

    async def get(self, entity_id):
        """The entity's fields (with _id), or {} if it has none."""
        doc = await self.collection.find_one({"_id": entity_id}, self._projection())
        return self._fields(doc) or {}

    async def update(self, entity_id, fields, op="set"):
        """Apply an update operator ("set", "push", "pull", "unset", "inc", ...)
        to the entity's fields, creating the document if needed. Field names
        may use dot notation."""
        op = op if op.startswith("$") else "$" + op
        update = {op: {self._field(name): value for name, value in fields.items()}}
        return await self.collection.update_one({"_id": entity_id}, update, upsert=True)

    async def find(self, query=None, *, batch_size=100):
        """Iterate over the fields (with _id) of entities matching `query`,
        whose keys name the entity's fields."""
        cursor = self.collection.find(self._query(query or {}), self._projection())
        if batch_size:
            cursor = cursor.batch_size(batch_size)
        async for doc in cursor:
            fields = self._fields(doc)
            if fields is not None:
                yield fields

    async def count(self, query=None):
        return await self.collection.count_documents(self._query(query or {}))


class ConfigRepo:
    """The bot's single config document (caches, emoji ids, ...)."""

    def __init__(self, collection, selector):
        self.collection = collection
        # How the document is found, e.g. {"cog_name": "GuildWars2"}
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
