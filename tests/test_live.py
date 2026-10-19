"""Contract tests against the live GW2 API.

Run with `pytest -m live`. They check that responses still contain the
fields the bot reads. Authenticated tests need GW2_API_KEY and are skipped
without it. They deliberately use plain aiohttp rather than the bot's client.
"""
import os

import aiohttp
import pytest

from gw2bot.cogs.guildwars2.daily import ACHIEVEMENT_CATEGORIES, CATEGORY_SCHEMA

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


async def test_wvw_matches(client, gamedata):
    matches = await get(client, "wvw/matches?ids=all")
    assert matches
    for match in matches:
        for key in "scores", "victory_points", "kills", "deaths", "all_worlds":
            assert {"red", "blue", "green"} <= match[key].keys(), key
        for m in match["maps"]:
            for objective in m["objectives"]:
                assert {"owner", "points_tick"} <= objective.keys()
        # Team names aren't in the API; gamedata copies the wiki's list
        teams = [i for ids in match["all_worlds"].values() for i in ids if i >= 10000]
        assert teams, match["id"]
        for team in teams:
            assert str(team) in gamedata["wvw_teams"], team


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


async def test_daily_achievement_categories(client):
    ids = ",".join(str(i) for i in ACHIEVEMENT_CATEGORIES.values())
    categories = await get(client, f"achievements/categories?ids={ids}&v={CATEGORY_SCHEMA}")
    assert {c["id"] for c in categories} == set(ACHIEVEMENT_CATEGORIES.values())
    for category in categories:
        assert category["achievements"], category["id"]
        assert category["tomorrow"], category["id"]
        achievement_ids = [a["id"] for a in category["achievements"] + category["tomorrow"]]
        achievements = await get(client, "achievements?ids=" + ",".join(map(str, achievement_ids)))
        assert all(a["name"] for a in achievements)


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


OBJECTIVE_FIELDS = {"title", "track", "acclaim", "progress_current", "progress_complete", "claimed"}


@needs_key
@pytest.mark.parametrize("period", ["daily", "weekly"])
async def test_wizards_vault(client, period):
    data = await get(client, f"account/wizardsvault/{period}", authenticated=True)
    assert {
        "meta_progress_current", "meta_progress_complete", "meta_reward_astral",
        "meta_reward_claimed", "objectives",
    } <= data.keys()
    assert all(OBJECTIVE_FIELDS <= o.keys() for o in data["objectives"])


@needs_key
async def test_wizards_vault_special(client):
    data = await get(client, "account/wizardsvault/special", authenticated=True)
    assert all(OBJECTIVE_FIELDS <= o.keys() for o in data["objectives"])


async def test_bot_client_against_live_api(client):
    """The bot's own client, end to end (the tests above deliberately aren't)."""
    from gw2bot.gw2api import APINotFound, Client

    api = Client(client)
    build, worlds = await api.get_many(["build", "worlds?ids=all"])
    assert isinstance(build["id"], int)
    assert worlds
    with pytest.raises(APINotFound):
        await api.get("items/999999999")


async def test_kp_achievements_exist(client, gamedata):
    from test_gamedata import kp_achievement_ids

    ids = sorted(kp_achievement_ids(gamedata))
    found = set()
    for start in range(0, len(ids), 200):
        chunk = ",".join(map(str, ids[start:start + 200]))
        found |= {a["id"] for a in await get(client, f"achievements?ids={chunk}")}
    assert not set(ids) - found, "unknown achievement ids in killproofs"
