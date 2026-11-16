"""The game data cache: copying items, skills and so on from the API."""

import subject

API = "https://api.guildwars2.com/v2/"


NAMES = {None: "Item", "de": "Gegenstand", "fr": "Objet", "es": "Objeto"}


def items(*ids, lang=None):
    return [{"id": i, "name": f"{NAMES[lang]} {i}", "rarity": "Fine"} for i in ids]


def in_every_language(*ids):
    """The API's responses for `ids` in English, German, French, Spanish."""
    return [(200, items(*ids, lang=lang)) for lang in NAMES]


async def test_cache_endpoint_in_batches_of_200():
    ids = list(range(1, 251))
    docs, requests = await subject.cache_endpoint(
        [(200, ids), *in_every_language(*ids[:200]), *in_every_language(*ids[200:])], "items"
    )
    assert sorted(docs) == ids
    first, second = (API + "items?ids=" + ",".join(map(str, batch)) for batch in (ids[:200], ids[200:]))
    assert requests == [
        (API + "items", None),
        (first, None), (first, "de"), (first, "fr"), (first, "es"),
        (second, None), (second, "de"), (second, "fr"), (second, "es"),
    ]


async def test_cached_documents_are_english_with_the_other_languages_text():
    docs, _ = await subject.cache_endpoint([(200, [1]), *in_every_language(1)], "items")
    # Only what differs: the rarity is the same enum in every language
    assert docs[1] == {
        "_id": 1,
        "name": "Item 1",
        "rarity": "Fine",
        "l10n": {"de": {"name": "Gegenstand 1"}, "fr": {"name": "Objet 1"}, "es": {"name": "Objeto 1"}},
    }


async def test_text_the_same_in_a_language_is_not_stored_again():
    karma = {"id": 2, "name": "Karma", "description": "Earned through activities."}
    german = {**karma, "description": "Kann durch verschiedene Aktivitäten verdient werden."}
    docs, _ = await subject.cache_endpoint(
        [(200, [2]), (200, [karma]), (200, [german]), (200, [karma]), (200, [karma])], "currencies", True
    )
    assert docs[2]["l10n"] == {"de": {"description": "Kann durch verschiedene Aktivitäten verdient werden."}}


async def test_nested_text_is_translated():
    food = {"id": 1, "name": "Banana", "type": "Consumable",
            "details": {"type": "Food", "duration_ms": 1800000, "description": "+40 Power"}}
    german = {**food, "name": "Banane", "details": {**food["details"], "description": "+40 Kraft"}}
    docs, _ = await subject.cache_endpoint(
        [(200, [1]), (200, [food]), (200, [german]), (200, [food]), (200, [food])], "items"
    )
    assert docs[1]["l10n"] == {"de": {"name": "Banane", "details": {"description": "+40 Kraft"}}}


async def test_endpoints_without_text_are_only_fetched_in_english():
    recipe = {"id": 7, "output_item_id": 1, "ingredients": []}
    docs, requests = await subject.cache_endpoint([(200, [7]), (200, [recipe])], "recipes")
    assert docs[7] == {"_id": 7, "output_item_id": 1, "ingredients": []}
    assert [lang for _, lang in requests] == [None, None]


async def test_cache_endpoint_all_at_once():
    docs, requests = await subject.cache_endpoint([(200, [1, 2]), *in_every_language(1, 2)], "pvp/amulets", True)
    assert sorted(docs) == [1, 2]
    assert requests == [
        (API + "pvp/amulets", None),
        (API + "pvp/amulets?ids=all", None),
        (API + "pvp/amulets?ids=all", "de"),
        (API + "pvp/amulets?ids=all", "fr"),
        (API + "pvp/amulets?ids=all", "es"),
    ]


async def test_cache_raids():
    raid = {"id": "forsaken_thicket", "wings": []}
    writes = await subject.cache_raids([(200, ["forsaken_thicket"]), (200, raid)])
    assert writes == [{"cache.raids": [raid]}]


def floor(*poi_ids):
    pois = {str(i): {"id": i, "name": f"POI {i}", "type": "landmark", "chat_link": "[&x]"} for i in poi_ids}
    return {"id": 1, "regions": {"1": {"maps": {"15": {"points_of_interest": pois}}}}}


async def test_cache_pois_names_in_every_language():
    def named(name):
        return {"id": 1, "regions": {"1": {"maps": {"15": {"points_of_interest": {
            "1": {"id": 1, "name": name, "type": "waypoint", "chat_link": "[&x]"}}}}}}}

    # The other languages' floors are fetched first, then English
    docs = await subject.cache_pois([
        (200, [{"id": 1}]),
        (200, [named("Löwenstein-Wegmarke")]),
        (200, [named("Point de passage de l'Arche du Lion")]),
        (200, [named("Lion's Arch Waypoint")]),  # The same as English: not stored
        (200, [named("Lion's Arch Waypoint")]),
    ])
    assert docs[1]["name"] == "Lion's Arch Waypoint"
    assert docs[1]["l10n"] == {"de": {"name": "Löwenstein-Wegmarke"},
                               "fr": {"name": "Point de passage de l'Arche du Lion"}}


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
    # Names are searched in every language
    names = ["name", "l10n.de.name", "l10n.fr.name", "l10n.es.name"]
    assert result["indexes"] == {
        "items": names, "achievements": names, "titles": names, "recipes": ["output_item_id"],
        "skins": names, "currencies": names, "skills": names,
    }


async def test_rebuild_tells_the_owner_about_failures():
    result = await subject.rebuild_cache(failing=["skins"])
    assert result["dms"] == ["Caching ['skins'] failed"]
    assert "skins" not in result["cached"]
    assert len(result["cached"]) == 16


# --- Fixes --------------------------------------------------------------------------------


async def test_cache_pois_writes_every_poi():
    docs = await subject.cache_pois([(200, [{"id": 1}]), (200, [floor(1, 2, 3)])])
    assert sorted(docs) == [1, 2, 3]


async def test_rebuild_finishes_when_the_owner_isnt_cached():
    result = await subject.rebuild_cache(failing=["skins"], owner_cached=False)
    assert result["error"] is None
    assert result["dms"] == ["Caching ['skins'] failed"]
    assert len(result["cached"]) == 16
    assert result["presence"][-1] == {}
