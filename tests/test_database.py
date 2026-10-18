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
from gw2bot.db import Data
from gw2bot.db.legacy import MongoController

URI = os.environ.get("MONGO_TEST_URI")
pytestmark = pytest.mark.skipif(not URI, reason="MONGO_TEST_URI not set")


# Storage layouts the repositories support; the same behaviour is expected
# from each
LAYOUTS = ["legacy"]


@pytest.fixture(params=LAYOUTS)
async def data(request):
    data = Data(URI, f"gw2bot_test_{uuid.uuid4().hex[:12]}")
    yield data
    await data.client.drop_database(data.db.name)
    await data.close()


# --- Settings repositories --------------------------------------------------


async def test_get_and_update(data):
    await data.users.update(1, {"key": {"account_name": "Example.1234"}})
    assert await data.users.get(1) == {"_id": 1, "key": {"account_name": "Example.1234"}}


async def test_missing_entity_is_empty(data):
    assert await data.users.get(404) == {}
    assert await data.guilds.get(404) == {}


async def test_update_merges_fields_and_dot_notation(data):
    await data.guilds.update(10, {"updates": {"on": True, "channel": 100}})
    await data.guilds.update(10, {"updates.mention": "here", "timezone": 2})
    assert await data.guilds.get(10) == {
        "_id": 10,
        "updates": {"on": True, "channel": 100, "mention": "here"},
        "timezone": 2,
    }


async def test_update_operators(data):
    await data.users.update(1, {"name_changes": ["Old.1", "New.2"]}, op="push")
    await data.users.update(1, {"name_changes": ["New.2", "Newer.3"]}, op="$push")
    await data.users.update(1, {"event_reminders": {"name": "a", "last_message": 5}}, op="push")
    await data.users.update(1, {"event_reminders": {"name": "b", "last_message": 6}}, op="push")
    result = await data.users.update(1, {"event_reminders": {"last_message": 5}}, op="pull")
    assert result.modified_count == 1
    await data.users.update(1, {"counter": 2}, op="inc")
    await data.users.update(1, {"gemtrack": 100})
    await data.users.update(1, {"gemtrack": ""}, op="unset")
    assert await data.users.get(1) == {
        "_id": 1,
        "name_changes": [["Old.1", "New.2"], ["New.2", "Newer.3"]],
        "event_reminders": [{"name": "b", "last_message": 6}],
        "counter": 2,
    }


async def test_entities_are_separate(data):
    await data.users.update(1, {"x": "user"})
    await data.guilds.update(1, {"x": "guild"})
    await data.channels.update(1, {"x": "channel"})
    assert (await data.users.get(1))["x"] == "user"
    assert (await data.guilds.get(1))["x"] == "guild"
    assert (await data.channels.get(1))["x"] == "channel"


async def test_find_with_queries_on_fields(data):
    await data.guilds.update(10, {"updates": {"on": True, "channel": 100}})
    await data.guilds.update(11, {"updates": {"on": False, "channel": 101}})
    await data.guilds.update(12, {"updates": {"on": True, "channel": None}})
    await data.guilds.update(13, {"timezone": 1})
    found = [doc async for doc in data.guilds.find({"updates.on": True, "updates.channel": {"$ne": None}})]
    assert found == [{"_id": 10, "updates": {"on": True, "channel": 100}}]


async def test_find_with_or(data):
    await data.users.update(1, {"key": {"account_name": "A.1"}, "keys": [{"account_name": "A.1"}]})
    await data.users.update(2, {"key": {"account_name": "B.2"}, "keys": [{"account_name": "B.2"}, {"account_name": "C.3"}]})
    await data.users.update(3, {"key": {"account_name": "D.4"}})

    async def users_with(name):
        query = {"$or": [{"key.account_name": name}, {"keys.account_name": name}]}
        return sorted([doc["_id"] async for doc in data.users.find(query)])

    assert await users_with("A.1") == [1]
    assert await users_with("C.3") == [2]
    assert await users_with("Z.9") == []


async def test_find_by_id_and_batch_size(data):
    for i in range(5):
        await data.users.update(i, {"public": i % 2 == 0})
    found = [doc["_id"] async for doc in data.users.find({"public": True}, batch_size=2)]
    assert sorted(found) == [0, 2, 4]
    assert [doc["_id"] async for doc in data.users.find({"_id": 3})] == [3]


async def test_count(data):
    await data.users.update(1, {"key": {"key": "A"}})
    await data.users.update(2, {"key": None})
    await data.users.update(3, {"other": True})
    assert await data.users.count({"key": {"$ne": None}}) == 1
    assert await data.users.count() == 3


# --- Config -------------------------------------------------------------------


async def test_config_defaults_then_only_new_keys(data):
    await data.config.ensure_defaults({"cache": {"build": 0}, "emojis": {}})
    await data.config.update({"cache.build": 123, "emojis.gold": 42})
    await data.config.ensure_defaults({"cache": {"build": 0}, "emojis": {}, "new": True})
    config = await data.config.get()
    assert config["cache"] == {"build": 123}
    assert config["emojis"] == {"gold": 42}
    assert config["new"] is True


# --- Compatibility with documents written by Toothy's MongoController -------


class GuildWars2:
    """Stands in for the cog: MongoController stores settings under its class name."""


def discord_object(spec, object_id):
    obj = MagicMock(spec=spec)
    obj.id = object_id
    return obj


@pytest.fixture
async def legacy():
    """A Data and a MongoController on the same, legacy-layout database."""
    name = f"gw2bot_test_{uuid.uuid4().hex[:12]}"
    bot = SimpleNamespace(get_user=lambda i: None, get_guild=lambda i: None)
    controller = MongoController(bot, URI, name)
    data = Data(URI, name)
    yield controller, data
    await data.client.drop_database(name)
    await data.close()
    await controller.client.close()


async def test_reads_settings_written_by_toothy(legacy):
    controller, data = legacy
    cog = GuildWars2()
    user = discord_object(discord.User, 1)
    guild = discord_object(discord.Guild, 10)
    await controller.set(user, {"key": {"key": "K", "account_name": "A.1"}, "keys": []}, cog)
    await controller.set(guild, {"updates.on": True, "updates.channel": 100}, cog)
    await controller.setup_cog(cog, {"cache": {"build": 5}, "emojis": {}})

    assert await data.users.get(1) == await controller.get(user, cog)
    assert await data.guilds.get(10) == {"_id": 10, "updates": {"on": True, "channel": 100}}
    assert (await data.config.get())["cache"] == {"build": 5}
    found = [doc async for doc in data.guilds.find({"updates.on": True})]
    assert found == [{"_id": 10, "updates": {"on": True, "channel": 100}}]


async def test_toothy_reads_settings_written_by_repositories(legacy):
    controller, data = legacy
    cog = GuildWars2()
    await data.users.update(1, {"key": {"key": "K", "account_name": "A.1"}})
    await data.users.update(1, {"name_changes": ["A.1", "B.2"]}, op="push")
    await data.config.ensure_defaults({"emojis": {}})
    await data.config.update({"emojis.gold": 42})

    user = discord_object(discord.User, 1)
    assert await controller.get(user, cog) == {
        "_id": 1,
        "key": {"key": "K", "account_name": "A.1"},
        "name_changes": [["A.1", "B.2"]],
    }
    assert (await controller.get_cog_config(cog))["emojis"] == {"gold": 42}


async def test_other_cogs_data_is_ignored_and_kept(legacy):
    controller, data = legacy
    raw = data.db.users
    await raw.insert_one({"_id": 1, "cogs": {"Other": {"x": 1}}, "flags": ["beta"]})
    assert await data.users.get(1) == {}
    assert [doc async for doc in data.users.find()] == []
    await data.users.update(1, {"key": "K"})
    assert await raw.find_one({"_id": 1}) == {
        "_id": 1,
        "cogs": {"Other": {"x": 1}, "GuildWars2": {"key": "K"}},
        "flags": ["beta"],
    }


# --- Query patterns the cog uses on its gw2.* collections --------------------


async def test_cache_queries(data):
    items = data.gw2.items
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


async def test_achievement_points(data):
    achievements = data.gw2.achievements
    await achievements.insert_one(
        {"_id": 1, "flags": [], "tiers": [{"count": 1, "points": 5}, {"count": 5, "points": 10}]}
    )
    await achievements.insert_one({"_id": 2, "flags": ["Repeatable"], "tiers": [], "point_cap": 50})
    # 15000 is the AP baseline for daily and monthly achievements
    assert await subject.total_possible_ap(data.gw2) == 15000 + 15 + 50
    progress = [{"id": 1, "current": 5}, {"id": 999, "current": 1}]
    assert await subject.account_ap(data.gw2, progress, {"daily_ap": 100, "monthly_ap": 20}) == 135
