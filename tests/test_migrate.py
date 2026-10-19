"""Copying GW2Bot's data out of the Toothy-era database.

Runs against a real MongoDB; skipped unless MONGO_TEST_URI is set (see
tests/test_database.py).
"""
import datetime
import os
import uuid
from unittest.mock import AsyncMock

import pytest
from pymongo import ASCENDING, AsyncMongoClient

from gw2bot.db.migrate import BATCH_SIZE, MigrationError, migrate

URI = os.environ.get("MONGO_TEST_URI")
pytestmark = pytest.mark.skipif(not URI, reason="MONGO_TEST_URI not set")

PROMPTS_TTL = 259200
NOW = datetime.datetime(2026, 10, 19, 12, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
async def mongo():
    """(client, source name, target name), both databases dropped afterwards."""
    client = AsyncMongoClient(URI, tz_aware=True)
    suffix = uuid.uuid4().hex[:10]
    source, target = f"toothy_{suffix}", f"gw2bot_{suffix}"
    yield client, source, target
    await client.drop_database(source)
    await client.drop_database(target)
    await client.close()


def key(token, name):
    return {"key": token, "account_name": name, "permissions": ["account"]}


async def seed(db):
    """A Toothy-style database as production has it."""
    await db.users.insert_many([
        {"_id": 1, "cogs": {"GuildWars2": {"key": key("K1", "A.1"), "keys": [key("K1", "A.1")]}}},
        # Another cog's data and Toothy fields stay behind
        {"_id": 2, "cogs": {"GuildWars2": {"gemtrack": 100}, "Music": {"volume": 5}}, "flags": ["beta"]},
        {"_id": 3, "cogs": {"Music": {"volume": 1}}},
        {"_id": 4, "embed_color": "0xffffff"},
    ])
    await db.guilds.insert_many([
        {"_id": 10, "cogs": {"GuildWars2": {"updates": {"on": True, "channel": 100}, "timezone": 2}}},
        {"_id": 11, "prefixes": ["!"]},
    ])
    await db.channels.insert_one({"_id": 500, "cogs": {"GuildWars2": {"evtc": {"enabled": True}}}})
    await db.configs.insert_many([
        {"cog_name": "GuildWars2", "cache": {"build": 123}, "emojis": {"gold": 42}},
        {"cog_name": "Music", "volume": 3},
    ])
    await db["gw2.items"].insert_many([{"_id": i, "name": f"Item {i}"} for i in range(3)])
    await db["gw2.items"].create_index([("name", ASCENDING)])
    await db["gw2.guildsync_prompts"].insert_one({"_id": "p1", "created_at": NOW})
    await db["gw2.guildsync_prompts"].create_index("created_at", expireAfterSeconds=PROMPTS_TTL)
    await db["gw2.evtc.api_keys"].insert_one({"_id": 1, "user": 1, "token": "T"})
    await db["gw2.guildsyncs"].insert_one({"_id": "s1", "guild_id": 10, "gid": "G"})
    await db["statistics.gw2"].insert_one({"_id": "link_previews", "item": 7})
    await db["gw2bot_state"].insert_one({"_id": "command_tree", "hash": "abc"})
    await db["music.queue"].insert_one({"_id": 1})
    # Leftovers of removed features
    await db["gw2.bosskills"].insert_one({"_id": 1, "week": 1})
    await db["gw2.worldpopulation"].insert_one({"_id": 1})


async def dump(db):
    """{collection: sorted documents} for a whole database."""
    result = {}
    for name in sorted(await db.list_collection_names()):
        docs = await db[name].find({}).to_list(None)
        result[name] = sorted(docs, key=lambda d: str(d["_id"]))
    return result


async def index_specs(collection):
    return {
        index["name"]: (dict(index["key"]), index.get("expireAfterSeconds"))
        async for index in await collection.list_indexes()
    }


async def test_copies_everything_gw2bot_uses(mongo):
    client, source, target = mongo
    await seed(client[source])
    report = await migrate(client, source, target)
    db = client[target]

    assert await db.users.find({}).sort("_id", 1).to_list(None) == [
        {"_id": 1, "key": key("K1", "A.1"), "keys": [key("K1", "A.1")]},
        {"_id": 2, "gemtrack": 100},
    ]
    assert await db.guilds.find({}).to_list(None) == [
        {"_id": 10, "updates": {"on": True, "channel": 100}, "timezone": 2}
    ]
    assert await db.channels.find({}).to_list(None) == [{"_id": 500, "evtc": {"enabled": True}}]
    assert await db.config.find({}).to_list(None) == [
        {"_id": "GuildWars2", "cache": {"build": 123}, "emojis": {"gold": 42}}
    ]
    assert len(await db.items.find({}).to_list(None)) == 3
    assert await db["evtc.api_keys"].find_one({"_id": 1}) == {"_id": 1, "user": 1, "token": "T"}
    assert await db.guildsyncs.count_documents({}) == 1
    assert await db.statistics.find_one({"_id": "link_previews"}) == {"_id": "link_previews", "item": 7}
    assert await db.state.find_one({"_id": "command_tree"}) == {"_id": "command_tree", "hash": "abc"}

    assert sorted(await db.list_collection_names()) == [
        "channels", "config", "evtc.api_keys", "guilds", "guildsync_prompts",
        "guildsyncs", "items", "state", "statistics", "users",
    ]
    assert report.counts == {
        "users": 2, "guilds": 1, "channels": 1, "config": 1, "evtc.api_keys": 1,
        "guildsync_prompts": 1, "guildsyncs": 1, "items": 3, "statistics": 1, "state": 1,
    }
    marker = await db.state.find_one({"_id": "schema"})
    assert marker["version"] == 1
    assert marker["migrated_from"] == source
    assert marker["counts"] == report.counts


async def test_copies_indexes_including_ttl(mongo):
    client, source, target = mongo
    await seed(client[source])
    await migrate(client, source, target)
    items = await index_specs(client[target].items)
    assert items["name_1"] == ({"name": 1}, None)
    prompts = await index_specs(client[target].guildsync_prompts)
    assert prompts["created_at_1"] == ({"created_at": 1}, PROMPTS_TTL)


async def test_leftover_collections_stay_behind(mongo):
    from gw2bot.db.migrate import NOT_COPIED

    client, source, target = mongo
    await seed(client[source])
    report = await migrate(client, source, target)
    copied = set(await client[target].list_collection_names())
    assert not copied & {name.removeprefix("gw2.") for name in NOT_COPIED}
    assert "bosskills" not in report.counts
    assert await client[source]["gw2.bosskills"].count_documents({}) == 1


async def test_source_is_left_untouched(mongo):
    client, source, target = mongo
    await seed(client[source])
    before = await dump(client[source])
    await migrate(client, source, target)
    assert await dump(client[source]) == before


async def test_runs_once(mongo):
    client, source, target = mongo
    await seed(client[source])
    await migrate(client, source, target)
    # Changes made in the new database after migrating are kept
    await client[target].users.update_one({"_id": 2}, {"$set": {"gemtrack": 200}})
    report = await migrate(client, source, target)
    assert report.skipped == "already done"
    assert report.counts == {}
    assert (await client[target].users.find_one({"_id": 2}))["gemtrack"] == 200


async def test_force_copies_again(mongo):
    client, source, target = mongo
    await seed(client[source])
    await migrate(client, source, target)
    await client[target].users.update_one({"_id": 2}, {"$set": {"gemtrack": 200}})
    await client[source].users.update_one({"_id": 2}, {"$set": {"cogs.GuildWars2.gemtrack": 300}})
    report = await migrate(client, source, target, force=True)
    assert report.counts["users"] == 2
    assert (await client[target].users.find_one({"_id": 2}))["gemtrack"] == 300


async def test_completes_an_interrupted_copy(mongo):
    client, source, target = mongo
    await seed(client[source])
    # A copy that died partway: some documents there, no marker
    await client[target].users.insert_one({"_id": 1, "key": "stale"})
    await client[target].items.insert_one({"_id": 0, "name": "Item 0"})
    await migrate(client, source, target)
    assert (await client[target].users.find_one({"_id": 1}))["key"] == key("K1", "A.1")
    assert await client[target].items.count_documents({}) == 3


async def test_large_collections_are_copied_in_batches(mongo):
    client, source, target = mongo
    count = BATCH_SIZE * 2 + 7
    await client[source]["gw2.items"].insert_many([{"_id": i} for i in range(count)])
    report = await migrate(client, source, target)
    assert report.counts["items"] == count
    assert await client[target].items.count_documents({}) == count


async def test_new_installation_has_nothing_to_copy(mongo):
    client, source, target = mongo
    report = await migrate(client, source, target)
    assert report.skipped.startswith("no source database")
    assert (await client[target].state.find_one({"_id": "schema"}))["migrated_from"] is None
    assert source not in await client.list_database_names()
    # and isn't copied later if one appears
    await seed(client[source])
    assert (await migrate(client, source, target)).skipped == "already done"


async def test_dry_run_writes_nothing(mongo):
    client, source, target = mongo
    await seed(client[source])
    dry = await migrate(client, source, target, dry_run=True)
    assert target not in await client.list_database_names()
    real = await migrate(client, source, target)
    assert dry.dry_run and dry.counts == real.counts
    assert "Would copy 13 documents" in dry.summary()


async def test_refuses_to_migrate_into_itself(mongo):
    client, source, _ = mongo
    with pytest.raises(MigrationError):
        await migrate(client, source, source)


# --- At startup ------------------------------------------------------------------


async def test_bot_migrates_on_first_start_only(mongo):
    from gw2bot.bot import GW2Bot
    from gw2bot.config import Settings

    client, source, target = mongo
    await seed(client[source])
    settings = Settings(token="unused", mongo_uri=URI, mongo_db=target, migrate_from_db=source, auto_sync=False)

    async def start():
        """Run the bot's startup (without its extensions); the stored account name."""
        bot = GW2Bot(settings)
        bot.load_extension = AsyncMock()
        try:
            await bot.setup_hook()
            assert (await bot.data.config.get())["emojis"] == {"gold": 42}
            return (await bot.data.users.get(1))["key"]["account_name"]
        finally:
            await bot.session.close()
            await bot.data.close()

    assert await start() == "A.1"
    await client[target].users.update_one({"_id": 1}, {"$set": {"key.account_name": "Renamed.1"}})
    # The second start doesn't copy over changes made since
    assert await start() == "Renamed.1"
