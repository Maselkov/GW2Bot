"""/tp and /gem commands."""
import pytest

import subject

API = "https://api.guildwars2.com/v2/"

# Cached item documents (public game data)
ECTO = {
    "_id": 19721, "name": "Glob of Ectoplasm", "level": 0, "rarity": "Exotic",
    "type": "CraftingMaterial", "icon": "https://render/ecto.png", "chat_link": "[&AgHJTQAA]", "flags": [],
}
SIGIL = {
    "_id": 24615, "name": "Superior Sigil of Force", "level": 60, "rarity": "Exotic",
    "type": "UpgradeComponent", "icon": "https://render/sigil.png", "chat_link": "[&AgEnYAAA]", "flags": [],
}
BOUND = {
    "_id": 1, "name": "Glob of Something Bound", "level": 0, "rarity": "Fine",
    "type": "Trophy", "chat_link": "[&AgEBAAAA]", "flags": ["AccountBound"],
}
ITEMS = [ECTO, SIGIL, BOUND]

# Synthetic trading post data for one account
SELLS = [
    {"id": 1, "item_id": 19721, "price": 1500, "quantity": 5},
    {"id": 2, "item_id": 24615, "price": 250000, "quantity": 1},
]
LISTINGS = [
    {"id": 19721,
     "buys": [{"listings": 20, "unit_price": 1350, "quantity": 5000}],
     "sells": [{"listings": 10, "unit_price": 1400, "quantity": 2500},
               {"listings": 3, "unit_price": 1500, "quantity": 750},
               {"listings": 7, "unit_price": 1600, "quantity": 1}]},
    {"id": 24615,
     "buys": [{"listings": 4, "unit_price": 240000, "quantity": 4}],
     "sells": [{"listings": 2, "unit_price": 249000, "quantity": 2},
               {"listings": 1, "unit_price": 250000, "quantity": 1}]},
]


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


# --- /tp selling, /tp buying ------------------------------------------------------


async def test_selling():
    embed, requests = await subject.commerce("tp_selling", [(200, SELLS), (200, LISTINGS)], items=ITEMS)
    assert embed["description"] == "Current sells"
    assert embed["author"]["name"] == "Transaction overview of Example.1234"
    assert embed["footer"]["text"] == "Black Lion Trading Company"
    # Coins use the gold/silver/copper emojis, or their names without them;
    # undercuts count the offers at or below your price
    assert fields(embed) == [
        ("Glob of Ectoplasm", "5 x 15 silver  - Total: 75 silver \nMax. offer: 14 silver  · Undercuts: 13"),
        ("Superior Sigil of Force", "1 x 25 gold \nMax. offer: 24 gold 90 silver  · Undercuts: 3"),
    ]
    assert requests == [
        (API + "commerce/transactions/current/sells", {"access_token": "KEY"}),
        (API + "commerce/listings?ids=19721,24615,", {}),
    ]


async def test_buying_counts_higher_offers():
    buys = [{"id": 3, "item_id": 19721, "price": 1300, "quantity": 2}]
    embed, requests = await subject.commerce("tp_buying", [(200, buys), (200, LISTINGS[:1])], items=ITEMS)
    assert embed["description"] == "Current buys"
    assert fields(embed) == [
        ("Glob of Ectoplasm", "2 x 13 silver  - Total: 26 silver \nMax. offer: 13 silver 50 copper  · Undercuts: 20"),
    ]
    assert requests[0][0] == API + "commerce/transactions/current/buys"


async def test_no_transactions():
    sent, _ = await subject.commerce("tp_selling", [(200, []), (400, {"text": "all ids provided are invalid"})])
    assert sent == "You don't have any ongoing transactions"


async def test_transactions_need_tradingpost_permission():
    from gw2bot.gw2api.errors import APIKeyError

    with pytest.raises(APIKeyError, match="`tradingpost`"):
        await subject.commerce("tp_selling", [(200, SELLS)], permissions=["account"])


# --- /tp price ------------------------------------------------------------------------


async def test_price(gamedata):
    prices = {"id": 19721, "buys": {"quantity": 900, "unit_price": 1598}, "sells": {"quantity": 2000, "unit_price": 1672}}
    embed, requests = await subject.commerce("tp_price", [(200, prices)], items=ITEMS, item="19721")
    assert embed["title"] == "Glob of Ectoplasm"
    assert embed["description"] == "A level 0 exotic crafting material"
    assert embed["color"] == int(gamedata["items"]["rarity_colors"]["Exotic"], 0)
    assert embed["thumbnail"]["url"] == "https://render/ecto.png"
    assert fields(embed) == [("Buy price", "15 silver 98 copper "), ("Sell price", "16 silver 72 copper ")]
    assert embed["footer"]["text"] == "[&AgHJTQAA]"
    assert requests == [(API + "commerce/prices/19721", {})]


async def test_price_without_orders():
    prices = {"id": 24615, "buys": {"quantity": 0, "unit_price": 0}, "sells": {"quantity": 0, "unit_price": 0}}
    embed, _ = await subject.commerce("tp_price", [(200, prices)], items=ITEMS, item="24615")
    assert fields(embed) == [("Buy price", "No buy orders"), ("Sell price", "No sell orders")]


async def test_price_not_on_trading_post():
    sent, _ = await subject.commerce("tp_price", [(404, {"text": "no such id"})], items=ITEMS, item="1")
    assert sent == "This item isn't on the TP."


async def test_price_autocomplete():
    assert await subject.tp_item_search("glob", ITEMS) == [("Glob of Ectoplasm", "19721")]
    assert await subject.tp_item_search("", ITEMS) == []
    assert await subject.tp_item_search("S", ITEMS) == [
        ("Glob of Ectoplasm", "19721"),
        ("Superior Sigil of Force", "24615"),
    ]


# --- /tp delivery ---------------------------------------------------------------------


async def test_delivery():
    box = {"coins": 12345, "items": [{"id": 19721, "count": 3}, {"id": 24615, "count": 1}]}
    embed, requests = await subject.commerce("tp_delivery", [(200, box)], items=ITEMS)
    assert embed["description"] == "Current deliveries"
    assert embed["author"]["name"] == "Delivery overview of Example.1234"
    assert fields(embed) == [
        ("Coins", "1 gold 23 silver 45 copper "),
        ("Glob of Ectoplasm", "x 3"),
        ("Superior Sigil of Force", "x 1"),
    ]
    assert requests == [(API + "commerce/delivery/", {"access_token": "KEY"})]


async def test_delivery_with_only_coins():
    embed, _ = await subject.commerce("tp_delivery", [(200, {"coins": 500, "items": []})], items=ITEMS)
    assert fields(embed) == [("Coins", "5 silver "), ("No current deliveries.", "Have fun!")]


async def test_empty_delivery_box():
    sent, _ = await subject.commerce("tp_delivery", [(200, {"coins": 0, "items": []})], items=ITEMS)
    assert sent == "Your delivery box is empty!"


# --- /gem price, /gem track -----------------------------------------------------------


async def test_gem_price():
    responses = [(200, {"coins_per_gem": 2500, "quantity": 4000}), (200, {"coins_per_gem": 1800, "quantity": 720000})]
    embed, requests = await subject.commerce("gem_price", responses)
    assert embed["title"] == "Currency exchange"
    # 400 gems at 2500 copper each; 400 gems sell for 72 gold
    assert fields(embed) == [("400 gems would cost you", "100 gold "), ("400 gems could buy you", "72 gold ")]
    assert [url for url, _ in requests] == [
        API + "commerce/exchange/coins?quantity=10000000",
        API + "commerce/exchange/gems?quantity=400",
    ]


async def test_gem_track():
    users = subject.FakeUserRepo(subject.stored_key(["account"]))
    sent, requests = await subject.commerce("gem_track", [], users=users, gold=50)
    assert sent == "You will be notified when price of 400 gems drops below 50 gold"
    assert users.writes == [("set", {"gemtrack": 500000})]
    assert requests == []


async def test_gem_track_rejects_out_of_range():
    users = subject.FakeUserRepo(subject.stored_key(["account"]))
    sent, _ = await subject.commerce("gem_track", [], users=users, gold=501)
    assert sent == "Invalid value. Gold may be between 0 and 500"
    assert users.writes == []


# --- Fixes ---------------------------------------------------------------------------


async def test_gem_price_rejects_tiny_quantities():
    sent, requests = await subject.commerce("gem_price", [], quantity=1)
    assert sent == "Quantity must be higher than 1"
    assert requests == []


async def test_items_without_listings_keep_the_others_right():
    # The API leaves out items without listings, e.g. a sell order that
    # filled between the two requests
    sells = [
        {"id": 1, "item_id": 24615, "price": 250000, "quantity": 1},
        {"id": 2, "item_id": 19721, "price": 1500, "quantity": 5},
    ]
    embed, _ = await subject.commerce("tp_selling", [(200, sells), (200, LISTINGS[:1])], items=ITEMS)
    assert fields(embed) == [
        ("Superior Sigil of Force", "1 x 25 gold "),
        ("Glob of Ectoplasm", "5 x 15 silver  - Total: 75 silver \nMax. offer: 14 silver  · Undercuts: 13"),
    ]
