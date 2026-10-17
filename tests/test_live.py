"""Contract tests against the live GW2 API.

Run with `pytest -m live`. They check that responses still contain the
fields the bot reads. Authenticated tests need GW2_API_KEY and are skipped
without it. They deliberately use plain aiohttp rather than the bot's client.
"""
import os

import aiohttp
import pytest

pytestmark = pytest.mark.live

API = "https://api.guildwars2.com/v2/"
KEY = os.environ.get("GW2_API_KEY")
needs_key = pytest.mark.skipif(not KEY, reason="GW2_API_KEY not set")

# Fact types SkillsMixin.get_skill_fields knows how to order; any other type
# makes it raise ValueError.
KNOWN_FACT_TYPES = {
    "Recharge", "ResourceCost", "Damage", "Percent", "AttributeAdjust",
    "BuffConversion", "Buff", "PrefixedBuff", "Number", "Radius", "Duration",
    "Time", "Distance", "ComboField", "Heal", "HealingAdjust", "NoData",
    "Unblockable", "Range", "ComboFinisher", "StunBreak",
}


@pytest.fixture
async def client():
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "GW2Bot tests"}) as c:
        yield c


async def get(client, endpoint, authenticated=False):
    params = {"access_token": KEY} if authenticated else None
    async with client.get(API + endpoint, params=params) as r:
        assert r.status in (200, 206), (endpoint, r.status, (await r.text())[:200])
        return await r.json()


async def test_build(client):
    assert isinstance((await get(client, "build"))["id"], int)


async def test_worlds(client):
    worlds = await get(client, "worlds?ids=all")
    assert worlds
    for world in worlds:
        assert {"id", "name", "population"} <= world.keys()


async def test_item(client):
    item = await get(client, "items/46762")
    assert {"id", "name", "type", "rarity", "icon"} <= item.keys()


async def test_item_rarities_are_known(client, gamedata):
    items = await get(client, "items?ids=19721,24575,24615,46762")
    for item in items:
        assert item["rarity"] in gamedata["items"]["rarity_colors"]


async def test_commerce_prices(client):
    price = await get(client, "commerce/prices/19721")
    assert isinstance(price["buys"]["unit_price"], int)
    assert isinstance(price["sells"]["unit_price"], int)


async def test_pvp_rank(client):
    assert (await get(client, "pvp/ranks/1"))["icon"]


async def test_skill_fact_types_are_known(client):
    skills = await get(client, "skills?page=0&page_size=200")
    unknown = {
        fact["type"]
        for skill in skills
        for fact in skill.get("facts", [])
        if fact["type"] not in KNOWN_FACT_TYPES
    }
    assert not unknown


@needs_key
async def test_account(client):
    account = await get(client, "account", authenticated=True)
    assert {"id", "name", "world", "guilds", "created"} <= account.keys()


@needs_key
async def test_pvp_stats(client):
    stats = await get(client, "pvp/stats", authenticated=True)
    assert {"pvp_rank", "pvp_rank_rollovers"} <= stats.keys()
    assert {"wins", "byes"} <= stats["aggregate"].keys()
    assert {"wins", "byes"} <= stats["ladders"]["ranked"].keys()


@needs_key
async def test_wallet(client):
    wallet = await get(client, "account/wallet", authenticated=True)
    assert all({"id", "value"} <= entry.keys() for entry in wallet)
