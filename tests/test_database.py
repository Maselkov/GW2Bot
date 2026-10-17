"""Data access against a real MongoDB.

Skipped unless MONGO_TEST_URI is set, e.g.:

    docker run -d --rm -p 127.0.0.1:27017:27017 mongo:9
    MONGO_TEST_URI=mongodb://localhost:27017 pytest tests/test_database.py

Each test gets its own database, dropped afterwards.
"""
import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest
from pymongo import ASCENDING, UpdateOne

import subject
from gw2bot.db.legacy import MongoController

URI = os.environ.get("MONGO_TEST_URI")
pytestmark = pytest.mark.skipif(not URI, reason="MONGO_TEST_URI not set")


class GuildWars2:
    """Stands in for the cog: settings are stored under its class name."""


COG = GuildWars2()


def user(user_id):
    obj = MagicMock(spec=discord.User)
    obj.id = user_id
    return obj


def guild(guild_id):
    obj = MagicMock(spec=discord.Guild)
    obj.id = guild_id
    return obj


@pytest.fixture
async def database():
    bot = SimpleNamespace(get_user=lambda i: f"user {i}", get_guild=lambda i: f"guild {i}")
    controller = MongoController(bot, URI, f"gw2bot_test_{uuid.uuid4().hex[:12]}")
    yield controller
    await controller.client.drop_database(controller.db.name)
    await controller.client.close()


async def test_cog_settings_roundtrip(database):
    alice = user(1)
    await database.set(alice, {"key": {"account_name": "Example.1234"}}, COG)
    assert await database.get(alice, COG) == {"_id": 1, "key": {"account_name": "Example.1234"}}
    assert await database.get_user(alice, COG) == {"_id": 1, "key": {"account_name": "Example.1234"}}
    full = await database.get(alice)
    assert full["cogs"]["GuildWars2"]["key"]["account_name"] == "Example.1234"


async def test_missing_documents(database):
    assert await database.get(user(404), COG) == {}
    assert await database.get(user(404)) == {}
    assert await database.get_user(user(404), COG) is None
    assert await database.get_guild(guild(404)) is None


async def test_set_merges_with_dot_notation(database):
    alice = user(1)
    await database.set(alice, {"key": "a"}, COG)
    await database.set(alice, {"keys": ["a", "b"]}, COG)
    assert await database.get(alice, COG) == {"_id": 1, "key": "a", "keys": ["a", "b"]}


async def test_set_operators(database):
    alice = user(1)
    await database.set(alice, {"name_changes": ["Old.1", "New.2"]}, COG, operator="push")
    await database.set(alice, {"name_changes": ["New.2", "Newer.3"]}, COG, operator="$push")
    doc = await database.get(alice, COG)
    assert doc["name_changes"] == [["Old.1", "New.2"], ["New.2", "Newer.3"]]


async def test_iter_yields_subdocuments_with_objects(database):
    await database.set_guild(guild(10), {"updates": {"on": True, "channel": 100}}, COG)
    await database.set_guild(guild(11), {"updates": {"on": False, "channel": 101}}, COG)
    await database.set_guild(guild(12), {"updates": {"on": True, "channel": None}}, COG)
    docs = [
        doc
        async for doc in database.iter(
            "guilds", {"updates.on": True, "updates.channel": {"$ne": None}}, COG, subdocs=["updates"]
        )
    ]
    assert docs == [{"on": True, "channel": 100, "_id": 10, "_obj": "guild 10"}]


async def test_cursors(database):
    for i in range(5):
        await database.set_user(user(i), {"public": i % 2 == 0}, COG)
    cursor = database.get_users_cursor({"public": True}, COG, batch_size=2)
    assert sorted([doc["_id"] async for doc in cursor]) == [0, 2, 4]


async def test_setup_cog_inserts_then_only_adds_new_keys(database):
    await database.setup_cog(COG, {"cache": {"build": 0}, "emojis": {}})
    await database.set_cog_config(COG, {"cache.build": 123})
    await database.setup_cog(COG, {"cache": {"build": 0}, "emojis": {}, "new": True})
    config = await database.get_cog_config(COG)
    assert config["cache"] == {"build": 123}
    assert config["new"] is True
    assert config["cog_name"] == "GuildWars2"


async def test_flags(database):
    alice = user(1)
    await database.set_flag(alice, beta=True)
    assert await database.get_flag(alice, "BETA") is True
    await database.set_flag(alice, beta=False)
    assert await database.get_flag(alice, "beta") is False


# --- Query patterns the cog uses on its gw2.* collections ------------------


async def test_cache_queries(database):
    items = database.db.gw2.items
    await items.create_index([("name", ASCENDING)])
    await items.bulk_write([
        UpdateOne({"_id": i}, {"$set": {"name": name, "rarity": "Exotic"}}, upsert=True)
        for i, name in enumerate(["Zojja's Claymore", "Zojja's Breastplate", "Glob of Ectoplasm"])
    ])
    assert await items.count_documents({}) == 3

    pattern = subject.search_pattern("zojja")
    found = await items.find({"name": pattern}).sort("name", 1).limit(25).to_list(25)
    assert [i["name"] for i in found] == ["Zojja's Breastplate", "Zojja's Claymore"]
    assert len(await items.find({}).to_list(None)) == 3
    assert await items.find_one({"_id": 2}, {"name": 1, "_id": 0}) == {"name": "Glob of Ectoplasm"}


async def test_achievement_points(database):
    achievements = database.db.gw2.achievements
    await achievements.insert_one(
        {"_id": 1, "flags": [], "tiers": [{"count": 1, "points": 5}, {"count": 5, "points": 10}]}
    )
    await achievements.insert_one({"_id": 2, "flags": ["Repeatable"], "tiers": [], "point_cap": 50})
    # 15000 is the AP baseline for daily and monthly achievements
    assert await subject.total_possible_ap(database.db.gw2) == 15000 + 15 + 50
    progress = [{"id": 1, "current": 5}, {"id": 999, "current": 1}]
    assert await subject.account_ap(database.db.gw2, progress, {"daily_ap": 100, "monthly_ap": 20}) == 135
