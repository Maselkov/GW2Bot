"""MongoDB: collections, and the users / guilds / channels settings."""
import copy
from types import SimpleNamespace


def _value(doc, name):
    """A (dotted) field of `doc`; through a list of documents, the list of
    their values."""
    value = doc
    for part in name.split("."):
        if isinstance(value, list):
            value = [v.get(part) for v in value if isinstance(v, dict)]
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _check(value, condition):
    """Whether a field's `value` meets a query `condition`, like Mongo:
    an array matches a plain value it contains."""
    if hasattr(condition, "search"):
        return isinstance(value, str) and bool(condition.search(value))
    if not isinstance(condition, dict):
        return value == condition or (isinstance(value, list) and condition in value)
    for op, operand in condition.items():
        if op == "$eq" and value != operand:
            return False
        if op == "$ne" and (value == operand or (isinstance(value, list) and operand in value)):
            return False
        if op == "$gte" and (value is None or value < operand):
            return False
        if op == "$lt" and (value is None or value >= operand):
            return False
        if op == "$in" and value not in operand:
            return False
        if op == "$nin" and set(value if isinstance(value, list) else [value]) & set(operand):
            return False
        if op == "$exists" and (value is not None) != operand:
            return False
    return True


def matches(doc, query):
    """Whether `doc` matches a Mongo `query` (with $or)."""
    for field, condition in (query or {}).items():
        if field == "$or":
            if not any(matches(doc, sub) for sub in condition):
                return False
        elif not _check(_value(doc, field), condition):
            return False
    return True


def _set(doc, name, value):
    """Set a (dotted) field; a number indexes an array, like Mongo."""
    *parents, last = name.split(".")
    for part in parents:
        doc = doc[int(part)] if isinstance(doc, list) else doc.setdefault(part, {})
    if isinstance(doc, list):
        doc[int(last)] = value
    else:
        doc[last] = value


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, field, direction=1):
        self.docs.sort(key=lambda doc: doc[field], reverse=direction == -1)
        return self

    def limit(self, length):
        del self.docs[length:]
        return self

    async def to_list(self, length):
        return self.docs[:length] if length else self.docs

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for doc in self.docs:
            yield doc


class MemoryCollection:
    """In-memory stand-in for a Mongo collection. Documents are in `docs`;
    like Mongo, documents without an _id get one. Indexes created are
    recorded in `indexes`."""

    def __init__(self, docs=()):
        self.docs = [{"_id": f"doc{i}", **d} for i, d in enumerate(docs)]
        self.indexes = []
        self._next_id = 0

    def find(self, query=None):
        return Cursor([dict(d) for d in self.docs if matches(d, query)])

    async def find_one(self, query):
        return next((dict(d) for d in self.docs if matches(d, query)), None)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if matches(d, query))

    async def insert_one(self, doc):
        self._next_id += 1
        doc.setdefault("_id", f"oid{self._next_id}")
        self.docs.append(dict(doc))

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if matches(doc, query):
                for name, value in update["$set"].items():
                    _set(doc, name, value)
                return

    async def delete_one(self, query):
        for i, doc in enumerate(self.docs):
            if matches(doc, query):
                del self.docs[i]
                return

    async def delete_many(self, query):
        self.docs = [d for d in self.docs if not matches(d, query)]

    async def bulk_write(self, requests):
        """ReplaceOne requests by _id, as the game data cache writes."""
        if not requests:
            from pymongo.errors import InvalidOperation

            raise InvalidOperation("No operations to execute")
        for request in requests:
            doc = request._doc
            self.docs = [d for d in self.docs if d["_id"] != doc["_id"]] + [doc]

    async def create_index(self, field, **options):
        self.indexes.append(field)


class MemoryDb:
    """A database (bot.data.gw2): a MemoryCollection per name, by
    attribute or item, created when first used."""

    def __init__(self, **collections):
        self.collections = {name: MemoryCollection(docs) for name, docs in collections.items()}

    def __getitem__(self, name):
        return self.collections.setdefault(name, MemoryCollection())

    def __getattr__(self, name):
        if name.startswith("_") or name == "collections":
            raise AttributeError(name)
        return self[name]

    def __setattr__(self, name, value):
        if name == "collections":
            super().__setattr__(name, value)
        else:
            self.collections[name] = value


def gw2_db(**collections):
    """The game data cache and other collections: {name: [documents]}."""
    return MemoryDb(**collections)


class MemorySettings:
    """Settings by Discord id, like bot.data.users / guilds / channels.

    Updates are applied (set, push and pull) and recorded in `writes` as
    (id, op, fields); find() takes Mongo queries on (dotted) fields.
    """

    def __init__(self, docs=None):
        # A copy: updates apply here, not to the test's own data
        self.docs = copy.deepcopy(docs or {})
        self.writes = []

    async def get(self, entity_id):
        doc = self.docs.get(entity_id)
        return {**doc, "_id": entity_id} if doc else {}

    async def update(self, entity_id, fields, op="set"):
        op = op.lstrip("$")
        self.writes.append((entity_id, op, fields))
        doc = self.docs.setdefault(entity_id, {})
        for name, value in fields.items():
            if op == "set":
                _set(doc, name, value)
            elif op == "push":
                doc.setdefault(name, []).append(value)
            elif op == "pull":
                doc[name] = [item for item in doc.get(name, []) if not matches(item, value)]
            elif op == "unset":
                doc.pop(name, None)
        return SimpleNamespace(modified_count=1)

    async def find(self, query=None, **kwargs):
        for entity_id, doc in list(self.docs.items()):
            if matches(doc, query):
                yield {**doc, "_id": entity_id}

    async def count(self, query=None):
        return sum(1 for doc in self.docs.values() if matches(doc, query))


class FakeUserRepo:
    """bot.data.users where every user has the same settings, `doc`.
    Writes are recorded as (op, fields)."""

    def __init__(self, doc):
        self.doc = doc
        self.writes = []

    async def get(self, user_id):
        return self.doc

    async def update(self, user_id, fields, op="set"):
        self.writes.append((op, fields))
