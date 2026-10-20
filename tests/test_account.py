"""/account, /li, /kp, /bosses, /search, /cats and /nodes."""
import datetime

import pytest

import subject

API = "https://api.guildwars2.com/v2/"
UTC = datetime.timezone.utc


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


def field(embed, name):
    return dict(fields(embed))[name]


def character(name, age=0, **details):
    """A synthetic /v2/characters entry."""
    return {"name": name, "race": "Human", "gender": "Female", "profession": "Guardian", "level": 80,
            "created": "2020-01-01T00:00:00Z", "age": age, "bags": [], "equipment_tabs": [], **details}


# --- /account ----------------------------------------------------------------------

# Synthetic /v2/account (never real account data)
ACCOUNT = {
    "name": "Example.1234",
    "created": "2015-08-28T00:00:00Z",
    "commander": True,
    "fractal_level": 100,
    "wvw": {"team_id": 11001, "rank": 1500},
    "access": ["GuildWars2", "HeartOfThorns", "PathOfFire", "EndOfDragons"],
    "daily_ap": 5000,
    "monthly_ap": 1000,
}


async def test_account_with_account_permission_only():
    embed, requests = await subject.account_command("account", [(200, ACCOUNT)])
    assert fields(embed) == [
        ("Created account on", "2015-08-28"),
        ("WvW team", "Moogooloo"),
        ("Commander tag", "Yes"),
        ("Fractal level", "100"),
        ("WvW rank", "1500"),
        ("Expansion access", "Heart Of Thorns\nPath Of Fire\nEnd Of Dragons"),
    ]
    assert embed["author"]["name"] == "Example.1234"
    assert embed["footer"]["text"] == "GW2Bot"
    assert requests == [(API + "account", {"access_token": "KEY"})]


async def test_account_with_every_permission():
    achievements = [
        {"_id": 1, "flags": [], "tiers": [{"count": 1, "points": 10}, {"count": 5, "points": 5}]},
        {"_id": 2, "flags": ["Repeatable"], "point_cap": 100, "tiers": [{"count": 1, "points": 5}]},
    ]
    progress = [{"id": 1, "current": 1, "done": False}]
    characters = [character("One", 3600), character("Two", 1800)]
    responses = [
        (200, ACCOUNT),
        (200, progress),
        (200, ACCOUNT),
        (200, {"pvp_rank": 80, "pvp_rank_rollovers": 5}),
        (200, characters),
    ]
    embed, requests = await subject.account_command(
        "account", responses, permissions=("account", "progression", "pvp", "characters"),
        db=subject.gw2_db(achievements=achievements),
    )
    # 15000 daily and monthly cap, 15 from tiers, 100 from the repeatable;
    # 6000 daily and monthly plus the first tier
    assert field(embed, "Achievement Points") == "6010 earned out of 15115 possible"
    assert field(embed, "PVP rank") == "85"
    assert field(embed, "Total time played") == "1 hours 30 minutes"
    assert [url for url, _ in requests] == [
        API + "account",
        API + "account/achievements",
        API + "account",
        API + "pvp/stats",
        API + "characters?page=0&page_size=200",
    ]


async def test_account_without_extras():
    account = {"name": "Example.1234", "created": "2020-01-01T00:00:00Z", "commander": False,
               "access": ["PlayForFree"]}
    embed, _ = await subject.account_command("account", [(200, account)])
    assert fields(embed) == [
        ("Created account on", "2020-01-01"),
        ("Commander tag", "No"),
        ("Expansion access", "Play For Free"),
    ]


# --- /li ----------------------------------------------------------------------------

INSIGHT, PERFECTED, REFINED = 77302, 80384, 80387


def storage(bank=(), characters=()):
    """account/bank, account/inventory, account/materials and characters."""
    return [(200, list(bank)), (200, []), (200, []), (200, list(characters))]


def wearing(*item_ids):
    return character("Character 1", equipment_tabs=[
        {"equipment": [{"id": i, "location": "Equipped"} for i in item_ids]},
    ])


async def test_li():
    responses = storage(bank=[{"id": INSIGHT, "count": 10}], characters=[wearing(PERFECTED, REFINED, REFINED)])
    responses.append((200, [{"id": 70, "value": 30}, {"id": 1, "value": 100}]))
    items = [{"_id": INSIGHT, "name": "Legendary Insight"}]
    embed, requests = await subject.account_command(
        "li", responses, permissions=("account", "inventories", "characters", "wallet"),
        db=subject.gw2_db(items=items),
    )
    assert embed["title"] == "65 Raid trophies earned"
    assert embed["description"] == "40 on hand, 25 used in crafting"
    # The first 6 armor pieces are worth less; refined armor that was
    # upgraded to perfected doesn't count twice
    assert fields(embed) == [
        ("65 Legendary Insights earned", "Wallet - **30**\nLegendary Insight - **10**\n1 Perfected Armor - **25**"),
    ]
    assert [url for url, _ in requests] == [
        API + "account/bank",
        API + "account/inventory",
        API + "account/materials",
        API + "characters?page=0&page_size=200",
        API + "account/wallet",
    ]


async def test_li_with_none_earned():
    responses = storage() + [(200, [])]
    embed, _ = await subject.account_command(
        "li", responses, permissions=("account", "inventories", "characters", "wallet"),
    )
    assert embed["title"] == "0 Raid trophies earned"
    assert "fields" not in embed


async def test_li_needs_wallet_permission():
    from gw2bot.gw2api.errors import APIKeyError

    with pytest.raises(APIKeyError, match="`wallet`"):
        await subject.account_command("li", [], permissions=("account", "inventories", "characters"))


# --- /kp ----------------------------------------------------------------------------


async def test_kp(gamedata):
    done = [
        {"id": 2654, "done": True},  # Vale Guardian
        {"id": 2667, "done": False, "current": 0},  # Gorseval
        {"id": 3998, "done": True},  # one of the three statues
        {"id": 5247, "current": 1, "done": False},  # Cold War, progressed
    ]
    embed, requests = await subject.account_command("kp", [(200, done)], permissions=("account", "progression"))
    assert embed["title"] == "Kill Proof"
    assert [name for name, _ in fields(embed)] == [a["name"] for a in gamedata["killproofs"]["areas"]]
    assert field(embed, "Spirit Vale") == "```diff\n+✔Vale Guardian\n-✖Gorseval\n-✖Sabetha\n```"
    assert "-✖Statues of Grenth" in field(embed, "Hall of Chains")
    assert "+✔Cold War" in field(embed, "Icebrood Saga Strike Missions")
    [(url, params)] = requests
    assert url.startswith(API + "account/achievements?ids=2654,2667,2659,")
    assert params == {"access_token": "KEY"}


async def test_kp_with_nothing_completed():
    # The API answers 404 when none of the ids have progress
    embed, _ = await subject.account_command(
        "kp", [(404, {"text": "all ids provided are invalid"})], permissions=("account", "progression")
    )
    assert field(embed, "Spirit Vale") == "```diff\n-✖Vale Guardian\n-✖Gorseval\n-✖Sabetha\n```"


# --- /bosses ------------------------------------------------------------------------

RAIDS = [{
    "id": "forsaken_thicket",
    "wings": [
        {"id": "spirit_vale", "events": [
            {"id": "vale_guardian", "type": "Boss"},
            {"id": "spirit_woods", "type": "Checkpoint"},
            {"id": "gorseval", "type": "Boss"},
            {"id": "sabetha", "type": "Boss"},
        ]},
        {"id": "salvation_pass", "events": [
            {"id": "slothasor", "type": "Boss"},
            {"id": "bandit_trio", "type": "Boss"},
            {"id": "matthias", "type": "Boss"},
        ]},
    ],
}]
# Logged in on Tuesday 5 March 2024; reset was Monday 07:30 UTC
BOSSES_ACCOUNT = {"name": "Example.1234", "last_modified": "2024-03-05T10:00:00Z"}
WEDNESDAY = datetime.datetime(2024, 3, 6, 12, tzinfo=UTC)


def encounter(boss_id, date, success, link):
    return {"boss_id": boss_id, "players": ["Example.1234", "Other.5678"], "date": date, "success": success,
            "permalink": link}


async def test_bosses():
    killed = ["vale_guardian", "spirit_woods", "gorseval", "sabetha", "slothasor"]
    embed, requests = await subject.account_command(
        "bosses", [(200, killed), (200, BOSSES_ACCOUNT)], permissions=("account", "progression"),
        raids=RAIDS, now=WEDNESDAY,
    )
    assert embed["title"] == "Bosses"
    assert embed["description"] == "2 bosses not completed this week"
    assert fields(embed) == [
        ("**Spirit Vale :white_check_mark:**",
         "> :white_check_mark:Vale Guardian\n> :white_check_mark:Spirit Woods\n"
         "> :white_check_mark:Gorseval\n> :white_check_mark:Sabetha"),
        ("**Salvation Pass :x:**", "> :white_check_mark:Slothasor\n> :x:Bandit Trio\n> :x:Matthias"),
    ]
    assert [url for url, _ in requests] == [API + "account/raids", API + "account"]


async def test_bosses_link_logs_from_this_week():
    vg = 15438
    encounters = [
        encounter(vg, datetime.datetime(2024, 3, 5, 20), True, "https://dps.report/new"),
        encounter(vg, datetime.datetime(2024, 3, 4, 20), True, "https://dps.report/old"),
        # Before reset, a failure, and someone else's
        encounter(vg, datetime.datetime(2024, 3, 4, 7), True, "https://dps.report/last-week"),
        encounter(vg, datetime.datetime(2024, 3, 5, 19), False, "https://dps.report/wipe"),
        {**encounter(vg, datetime.datetime(2024, 3, 5, 21), True, "https://dps.report/other"),
         "players": ["Other.5678"]},
    ]
    db = subject.gw2_db()
    db.encounters = subject.MemoryCollection(encounters)
    embed, _ = await subject.account_command(
        "bosses", [(200, ["vale_guardian"]), (200, BOSSES_ACCOUNT)], permissions=("account", "progression"),
        raids=RAIDS, now=WEDNESDAY, db=db,
    )
    assert fields(embed)[0][1].split("\n")[0] == (
        "> :white_check_mark:[Vale Guardian](https://dps.report/new) ([2](https://dps.report/old))"
    )


async def test_bosses_with_everything_done():
    killed = [e["id"] for wing in RAIDS[0]["wings"] for e in wing["events"]]
    embed, _ = await subject.account_command(
        "bosses", [(200, killed), (200, BOSSES_ACCOUNT)], permissions=("account", "progression"),
        raids=RAIDS, now=WEDNESDAY,
    )
    assert embed["description"] == "Everything completed this week :star:"


async def test_bosses_after_the_next_reset():
    embed, _ = await subject.account_command(
        "bosses", [(200, ["vale_guardian"]), (200, BOSSES_ACCOUNT)], permissions=("account", "progression"),
        raids=RAIDS, now=datetime.datetime(2024, 3, 12, 12, tzinfo=UTC),
    )
    assert embed["description"] == (
        "5 bosses, 1 event not completed that week\n"
        "❗Warning❗\n Data outdated for this week. Log into GW2 in order to update."
    )


# --- /search --------------------------------------------------------------------------

RUBY = 79280
RUBY_DOC = {"_id": RUBY, "name": "Ruby Orb", "rarity": "Masterwork", "type": "UpgradeComponent",
            "icon": "https://render/ruby.png"}
SEARCH_CHARACTER = character(
    "Character 1",
    bags=[{"id": 8932, "size": 20, "inventory": [{"id": RUBY, "count": 5}]}],
    equipment_tabs=[{"equipment": [{"id": 2, "location": "Equipped", "infusions": [RUBY]}]}],
)
SEARCH_PERMISSIONS = ("account", "inventories", "characters")


async def test_search(gamedata):
    responses = storage(bank=[{"id": RUBY, "count": 250}], characters=[SEARCH_CHARACTER])
    embed, requests = await subject.account_command(
        "search", responses, permissions=SEARCH_PERMISSIONS, db=subject.gw2_db(items=[RUBY_DOC]), item=str(RUBY),
    )
    assert embed["description"].startswith("Search results")
    assert embed["color"] == int(gamedata["items"]["rarity_colors"]["Masterwork"], 16)
    assert embed["thumbnail"]["url"] == "https://render/ruby.png"
    assert fields(embed) == [("Ruby Orb", "```ml\n" + "\n".join([
        "LOCATION      COUNT",
        "-------------|-----",
        "BANK         | 250",
        "CHARACTER 1  | 6",
        "--------------------",
        "TOTAL:         256",
    ]) + "\n```")]
    assert embed["author"]["name"] == "Example.1234"
    assert embed["footer"]["text"] == "GW2Bot"
    assert [url for url, _ in requests] == [
        API + "account/bank",
        API + "account/inventory",
        API + "account/materials",
        API + "characters?page=0&page_size=200",
    ]


async def test_search_by_typed_name():
    responses = storage(bank=[{"id": RUBY, "count": 1}])
    embed, _ = await subject.account_command(
        "search", responses, permissions=SEARCH_PERMISSIONS, db=subject.gw2_db(items=[RUBY_DOC]), item="ruby",
    )
    assert fields(embed)[0][0] == "Ruby Orb"


async def test_search_not_on_the_account():
    sent, _ = await subject.account_command(
        "search", storage(), permissions=SEARCH_PERMISSIONS, db=subject.gw2_db(items=[RUBY_DOC]), item=str(RUBY),
    )
    assert sent == "`Ruby Orb`: Not found on your account."


async def test_search_unknown_name():
    sent, requests = await subject.account_command(
        "search", [], permissions=SEARCH_PERMISSIONS, db=subject.gw2_db(items=[RUBY_DOC]), item="Anvil",
    )
    assert sent == "Could not find any items with that name."
    assert requests == []


async def test_search_autocomplete_merges_identical_items():
    items = [
        RUBY_DOC,
        {**RUBY_DOC, "_id": 1},
        {**RUBY_DOC, "_id": 2, "rarity": "Rare"},
        {"_id": 3, "name": "Pile of Rubies", "rarity": "Basic", "type": "CraftingMaterial"},
    ]
    assert await subject.account_item_search("rub", items) == [
        ("Pile of Rubies - Basic", "3"),
        ("Ruby Orb - Masterwork", "79280 1"),
        ("Ruby Orb - Rare", "2"),
    ]
    assert await subject.account_item_search("", items) == []


# --- /cats, /nodes --------------------------------------------------------------------


async def test_cats(gamedata):
    owned = [{"id": cat["id"]} for cat in gamedata["cats"][1:]]
    embed, requests = await subject.account_command("cats", [(200, owned)], permissions=("account", "progression"))
    assert fields(embed) == [("Cats you haven't collected yet", gamedata["cats"][0]["guide"])]
    assert requests == [(API + "account/home/cats", {"access_token": "KEY"})]


async def test_all_cats(gamedata):
    owned = [{"id": cat["id"]} for cat in gamedata["cats"]]
    sent, _ = await subject.account_command("cats", [(200, owned)], permissions=("account", "progression"))
    assert sent == "You have collected all the cats! Congratulations! :cat2:"


async def test_nodes(gamedata):
    owned = [node["id"] for node in gamedata["nodes"][2:]]
    embed, requests = await subject.account_command("nodes", [(200, owned)], permissions=("account", "progression"))
    assert fields(embed) == [
        ("Nodes you haven't collected yet:", "\n".join(n["guide"] for n in gamedata["nodes"][:2])),
    ]
    assert requests == [(API + "account/home/nodes", {"access_token": "KEY"})]


async def test_all_nodes(gamedata):
    owned = [node["id"] for node in gamedata["nodes"]]
    sent, _ = await subject.account_command("nodes", [(200, owned)], permissions=("account", "progression"))
    assert sent == "You've collected all home instance nodes! Congratulations!"


# --- Fixes ---------------------------------------------------------------------------


async def test_path_of_fire_implies_heart_of_thorns():
    account = {**ACCOUNT, "access": ["GuildWars2", "PathOfFire"]}
    embed, _ = await subject.account_command("account", [(200, account)])
    assert field(embed, "Expansion access") == "Path Of Fire\nHeart Of Thorns"


async def test_li_with_an_uncached_item():
    responses = storage(bank=[{"id": INSIGHT, "count": 10}]) + [(200, [])]
    embed, _ = await subject.account_command(
        "li", responses, permissions=("account", "inventories", "characters", "wallet"),
        db=subject.gw2_db(items=[]),
    )
    assert fields(embed) == [("10 Legendary Insights earned", "Unknown item - **10**")]
