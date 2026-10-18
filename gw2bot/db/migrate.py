"""One-time copy of GW2Bot's data out of the Toothy-era database.

Toothy stored GW2Bot's settings as `cogs.GuildWars2` subdocuments of its
shared users/guilds/channels collections, the config in `configs`, and
GW2Bot's own collections under a `gw2.` prefix. This copies all of it into
GW2Bot's database with plain names:

    users/guilds/channels.cogs.GuildWars2 -> users/guilds/channels
    configs {cog_name: "GuildWars2"}      -> config {_id: "GuildWars2"}
    gw2.<name>                            -> <name> (with its indexes),
                                             except leftovers of removed
                                             features (NOT_COPIED)
    statistics.gw2                        -> statistics
    gw2bot_state                          -> state

The source database is only read. The copy is recorded in the target's
`state` collection ({_id: "schema"}), written last, so an interrupted copy
is simply redone; it's idempotent.

Usage (same MONGO_* / MIGRATE_FROM_DB environment as the bot):

    python -m gw2bot.db.migrate --dry-run   # report what would be copied
    python -m gw2bot.db.migrate --force     # copy again over an existing copy
"""
import argparse
import asyncio
import dataclasses
import datetime
import logging
import os
import sys

from pymongo import AsyncMongoClient, ReplaceOne

from . import CONFIG_ID

log = logging.getLogger(__name__)

COG_NAME = "GuildWars2"
SETTINGS_COLLECTIONS = ["users", "guilds", "channels"]
SCHEMA_VERSION = 1
BATCH_SIZE = 1000
SAMPLE_SIZE = 50
INDEX_OPTIONS = ("name", "unique", "sparse", "expireAfterSeconds", "partialFilterExpression")
# gw2.* collections no code uses any more; they stay in the source database
NOT_COPIED = {
    "gw2.bosskills",  # weekly raid kills per account (1M+ documents in production)
    "gw2.maps",
    "gw2.worldpopulation",  # WvW population tracking, removed in #172
    "gw2.worlds",  # WvW worlds, replaced by teams in #174
}


class MigrationError(Exception):
    pass


@dataclasses.dataclass
class Report:
    source: str
    target: str
    dry_run: bool = False
    # Why nothing was copied, if nothing was
    skipped: str | None = None
    # Documents copied per target collection
    counts: dict = dataclasses.field(default_factory=dict)

    def summary(self):
        action = "Would copy" if self.dry_run else "Copied"
        if self.skipped:
            return f"Data migration from {self.source!r} to {self.target!r}: {self.skipped}"
        parts = ", ".join(f"{name}: {count}" for name, count in self.counts.items())
        return f"{action} {sum(self.counts.values())} documents from {self.source!r} to {self.target!r} ({parts})"


def target_name(source_collection):
    """Where a source collection is copied to, or None if it isn't."""
    if source_collection in NOT_COPIED:
        return None
    if source_collection.startswith("gw2."):
        return source_collection[len("gw2."):]
    return {"gw2": "gw2", "statistics.gw2": "statistics", "gw2bot_state": "state"}.get(source_collection)


async def migrate(client, source, target, *, dry_run=False, force=False):
    """Copy GW2Bot's data from database `source` into database `target`."""
    if source == target:
        raise MigrationError(f"Source and target are both {source!r}")
    report = Report(source, target, dry_run=dry_run)
    source_db, target_db = client[source], client[target]

    if not force and await target_db.state.find_one({"_id": "schema"}):
        report.skipped = "already done"
        return report
    if source not in await client.list_database_names():
        report.skipped = "no source database (new installation)"
        if not dry_run:
            await mark_migrated(target_db, None, {})
        return report

    samples = {}

    async def copy(name, docs):
        count, sample = await copy_documents(target_db[name], docs, dry_run=dry_run)
        report.counts[name] = report.counts.get(name, 0) + count
        samples.setdefault(name, []).extend(sample)

    for name in SETTINGS_COLLECTIONS:
        await copy(name, settings_documents(source_db[name]))

    config = await source_db.configs.find_one({"cog_name": COG_NAME})
    if config:
        fields = {k: v for k, v in config.items() if k not in ("_id", "cog_name")}
        await copy("config", one({"_id": CONFIG_ID, **fields}))

    collections = await source_db.list_collection_names(filter={"type": "collection"})
    for name in sorted(collections):
        destination = target_name(name)
        if destination is None:
            continue
        await copy(destination, source_db[name].find({}))
        if not dry_run:
            await copy_indexes(source_db[name], target_db[destination])

    if not dry_run:
        await verify(target_db, report.counts, samples)
        await mark_migrated(target_db, source, report.counts)
    return report


async def settings_documents(collection):
    path = f"cogs.{COG_NAME}"
    async for doc in collection.find({path: {"$exists": True}}, {path: 1}):
        fields = doc["cogs"][COG_NAME]
        if isinstance(fields, dict):
            yield {**fields, "_id": doc["_id"]}


async def one(doc):
    yield doc


async def copy_documents(collection, docs, *, dry_run):
    """Upsert documents by _id in batches. Returns (count, sample of ids)."""
    count = 0
    sample = []
    batch = []
    async for doc in docs:
        count += 1
        if len(sample) < SAMPLE_SIZE:
            sample.append(doc["_id"])
        if dry_run:
            continue
        batch.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
        if len(batch) >= BATCH_SIZE:
            await collection.bulk_write(batch, ordered=False)
            batch = []
    if batch:
        await collection.bulk_write(batch, ordered=False)
    return count, sample


async def copy_indexes(source, target):
    async for index in await source.list_indexes():
        if index["name"] == "_id_":
            continue
        options = {k: index[k] for k in INDEX_OPTIONS if k in index}
        await target.create_index(list(index["key"].items()), **options)


async def verify(target_db, counts, samples):
    for name, expected in counts.items():
        found = await target_db[name].count_documents({})
        if found < expected:
            raise MigrationError(f"{name}: {found} documents after copying {expected}")
        ids = samples.get(name, [])
        present = await target_db[name].count_documents({"_id": {"$in": ids}})
        if present != len(ids):
            raise MigrationError(f"{name}: {len(ids) - present} sampled documents are missing")


async def mark_migrated(target_db, source, counts):
    await target_db.state.replace_one(
        {"_id": "schema"},
        {
            "_id": "schema",
            "version": SCHEMA_VERSION,
            "migrated_from": source,
            "migrated_at": datetime.datetime.now(datetime.timezone.utc),
            "counts": counts,
        },
        upsert=True,
    )


def main(argv=None):
    from ..config import ConfigError, Settings, _mongo_uri

    parser = argparse.ArgumentParser(prog="python -m gw2bot.db.migrate", description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="only report what would be copied")
    parser.add_argument("--force", action="store_true", help="copy again even if already done")
    args = parser.parse_args(argv)

    env = os.environ
    uri = env.get("MONGO_URI") or _mongo_uri(env)
    try:
        settings = Settings(
            token="unused",
            mongo_uri=uri,
            mongo_db=env.get("MONGO_DB") or Settings.mongo_db,
            migrate_from_db=env.get("MIGRATE_FROM_DB") or Settings.migrate_from_db,
        )
    except ConfigError as e:
        sys.exit(f"Configuration error: {e}")

    async def run():
        client = AsyncMongoClient(settings.mongo_uri)
        try:
            return await migrate(
                client, settings.migrate_from_db, settings.mongo_db, dry_run=args.dry_run, force=args.force
            )
        finally:
            await client.close()

    report = asyncio.run(run())
    print(report.summary())


if __name__ == "__main__":
    main()
