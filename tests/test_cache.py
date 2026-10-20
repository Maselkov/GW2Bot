"""The game data cache: copying items, skills and so on from the API."""
import pytest

import subject

API = "https://api.guildwars2.com/v2/"


def items(*ids):
    return [{"id": i, "name": f"Item {i}"} for i in ids]


async def test_cache_endpoint_in_batches_of_200():
    ids = list(range(1, 251))
    docs, requests = await subject.cache_endpoint(
        [(200, ids), (200, items(*ids[:200])), (200, items(*ids[200:]))], "items"
    )
    assert sorted(docs) == ids
    assert docs[1] == {"_id": 1, "name": "Item 1"}
    assert requests == [
        API + "items",
        API + "items?ids=" + ",".join(map(str, ids[:200])),
        API + "items?ids=" + ",".join(map(str, ids[200:])),
    ]


async def test_cache_endpoint_all_at_once():
    docs, requests = await subject.cache_endpoint([(200, [1, 2]), (200, items(1, 2))], "pvp/amulets", True)
    assert sorted(docs) == [1, 2]
    assert requests == [API + "pvp/amulets", API + "pvp/amulets?ids=all"]


async def test_cache_raids():
    raid = {"id": "forsaken_thicket", "wings": []}
    writes = await subject.cache_raids([(200, ["forsaken_thicket"]), (200, raid)])
    assert writes == [{"cache.raids": [raid]}]


def floor(*poi_ids):
    pois = {str(i): {"id": i, "name": f"POI {i}", "type": "landmark", "chat_link": "[&x]"} for i in poi_ids}
    return {"id": 1, "regions": {"1": {"maps": {"15": {"points_of_interest": pois}}}}}


async def test_cache_pois_in_batches():
    docs = await subject.cache_pois([(200, [{"id": 1}]), (200, [floor(*range(1, 252))])])
    # Written 201 at a time
    assert 201 in docs
    assert docs[1] == {"_id": 1, "name": "POI 1", "type": "landmark", "continent_id": 1}


async def test_rebuild():
    result = await subject.rebuild_cache()
    assert result["error"] is None
    assert result["presence"][0] == {"activity": "Rebuilding API cache", "status": "dnd"}
    # Back to normal
    assert result["presence"][-1] == {}
    assert result["cached"][:3] == ["items", "achievements", "itemstats"]
    assert len(result["cached"]) == 17
    assert result["indexes"] == {
        "items": ["name"], "achievements": ["name"], "titles": ["name"], "recipes": ["output_item_id"],
        "skins": ["name"], "currencies": ["name"], "skills": ["name"],
    }


async def test_rebuild_tells_the_owner_about_failures():
    result = await subject.rebuild_cache(failing=["skins"])
    assert result["dms"] == ["Caching ['skins'] failed"]
    assert "skins" not in result["cached"]
    assert len(result["cached"]) == 16


# --- Known bugs ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="the last batch of points of interest is never written")
async def test_cache_pois_writes_every_poi():
    docs = await subject.cache_pois([(200, [{"id": 1}]), (200, [floor(1, 2, 3)])])
    assert sorted(docs) == [1, 2, 3]


@pytest.mark.xfail(strict=True, reason="with the owner not cached, a failure aborts the rebuild and the status stays")
async def test_rebuild_finishes_when_the_owner_isnt_cached():
    result = await subject.rebuild_cache(failing=["skins"], owner_cached=False)
    assert result["error"] is None
    assert result["dms"] == ["Caching ['skins'] failed"]
    assert len(result["cached"]) == 16
    assert result["presence"][-1] == {}
