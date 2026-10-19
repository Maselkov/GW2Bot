"""/achievement: an achievement's details and the user's progress."""
import subject

API = "https://api.guildwars2.com/v2/"

# Cached game data (synthetic, shaped like /v2/achievements and friends)
CHICKEN = {
    "_id": 1, "name": "Playing Chicken", "description": "<c=@flavor>Win a race.</c>",
    "requirement": "Win 3 races.", "icon": "https://render/chicken.png", "flags": [],
    "tiers": [{"count": 1, "points": 5}, {"count": 3, "points": 10}],
    "bits": [
        {"type": "Text", "text": "Race A"},
        {"type": "Item", "id": 19721},
        {"type": "Minipet", "id": 5},
        {"type": "Skin", "id": 7},
    ],
    "rewards": [
        {"type": "Coins", "count": 12345},
        {"type": "Item", "id": 19721, "count": 2},
        {"type": "Mastery", "id": 1, "region": "Tyria"},
        {"type": "Title", "id": 9},
    ],
}
REPEATABLE = {
    "_id": 2, "name": "Daily Grind", "description": "Again.", "flags": ["Repeatable"],
    "point_cap": 50, "tiers": [{"count": 1, "points": 5}, {"count": 3, "points": 10}],
}


def db():
    return subject.gw2_db(
        achievements=[CHICKEN, REPEATABLE],
        items=[{"_id": 19721, "name": "Glob of Ectoplasm"}],
        minis=[{"_id": 5, "name": "Mini Moa"}],
        skins=[{"_id": 7, "name": "Fancy Skin"}],
        titles=[{"_id": 9, "name": "Chicken Runner"}],
    )


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


async def test_achievement_in_progress():
    progress = {"id": 1, "current": 2, "max": 3, "done": False, "bits": [0, 2]}
    embed, requests = await subject.achievement([(200, progress)], "1", db=db())
    assert embed["title"] == "Playing Chicken"
    assert embed["description"] == "Win a race."
    assert embed["thumbnail"]["url"] == "https://render/chicken.png"
    assert fields(embed) == [
        ("Requirement", "Win 3 races."),
        ("Objectives (1/1)", "```diff\n+✔Race A\n-✖Glob of Ectoplasm\n+✔Mini Moa\n-✖Fancy Skin\n```"),
        ("Rewards", "1 gold 23 silver 45 copper \n2 Glob of Ectoplasm\nTyria Mastery Point\nTitle: Chicken Runner"),
        ("Tier completion", "1/2"),
        ("AP earned", "5/15"),
    ]
    assert embed["footer"]["text"] == "GW2Bot | Green (+) means completed. Red (-) means not | ID: 1"
    assert embed["author"]["name"] == "Example.1234"
    assert requests == [(API + "account/achievements?id=1", {"access_token": "KEY"})]


async def test_achievement_not_started():
    embed, _ = await subject.achievement([(404, {"text": "no such id"})], "1", db=db())
    assert ("Tier completion", "0/2") in fields(embed)
    assert ("AP earned", "0/15") in fields(embed)
    assert fields(embed)[1][1].count("-✖") == 4


async def test_repeatable_achievement_is_capped():
    progress = {"id": 2, "current": 3, "max": 3, "done": True, "repeated": 3}
    embed, _ = await subject.achievement([(200, progress)], "2", db=db())
    # 15 points per completion, 4 completions, capped at 50
    assert fields(embed) == [("Tier completion", "Completed\nRepeats: 3"), ("AP earned", "50/50")]


async def test_achievement_autocomplete():
    assert await subject.achievement_search("chick", db()) == [("Playing Chicken", "1")]
    assert await subject.achievement_search("", db()) == []


# --- Fixes ---------------------------------------------------------------------------


async def test_name_typed_without_picking_from_the_list():
    progress = {"id": 1, "current": 2, "max": 3, "done": False, "bits": []}
    embed, _ = await subject.achievement([(200, progress)], "playing chicken", db=db())
    assert embed["title"] == "Playing Chicken"


async def test_unknown_achievement():
    sent, requests = await subject.achievement([], "no such thing", db=db())
    assert sent == "No achievement found matching `no such thing`."
    assert requests == []
    sent, _ = await subject.achievement([], "999", db=db())
    assert sent == "No achievement found matching `999`."


async def test_objectives_and_rewards_missing_from_the_cache():
    progress = {"id": 1, "current": 2, "max": 3, "done": False, "bits": []}
    empty_cache = subject.gw2_db(achievements=[CHICKEN], items=[], minis=[], skins=[], titles=[])
    embed, _ = await subject.achievement([(200, progress)], "1", db=empty_cache)
    assert fields(embed)[1] == (
        "Objectives (1/1)", "```diff\n-✖Race A\n-✖Unknown item\n-✖Unknown miniature\n-✖Unknown skin\n```"
    )
    assert fields(embed)[2] == (
        "Rewards", "1 gold 23 silver 45 copper \n2 Unknown item\nTyria Mastery Point\nTitle: "
    )
