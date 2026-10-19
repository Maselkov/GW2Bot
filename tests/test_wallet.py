"""/wallet: currencies in the wallet, and currencies kept as items."""
import subject

API = "https://api.guildwars2.com/v2/"

NAMES = {1: "Coin", 4: "Gem", 28: "Magnetite Shard", 79280: "Blood Ruby", 46682: "1 Bandit Crest"}
CURRENCIES = [
    {"_id": i, "name": NAMES.get(i, f"Currency {i}"), "description": f"About currency {i}",
     "icon": f"https://render/currency/{i}.png"}
    for i in subject.WALLET_CURRENCY_IDS
]
ITEMS = [{"_id": i, "name": NAMES.get(i, f"Item {i}")} for i in subject.WALLET_ITEM_IDS]

# Synthetic account data
WALLET = [{"id": 1, "value": 1234567}, {"id": 4, "value": 500}, {"id": 28, "value": 7}]
BANK = [{"id": 79280, "count": 250}, None, {"id": 46682, "count": 3}]
MATERIALS = [{"id": 79280, "count": 100, "category": 37}]
OVERVIEW = [(200, WALLET), (200, BANK), (200, []), (200, MATERIALS), (200, [])]


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


def section(embed, name):
    return dict(fields(embed))[f"> **{name}**"].split("\n")


async def test_overview_sections():
    embed, requests = await subject.wallet(OVERVIEW, currencies=CURRENCIES, items=ITEMS)
    assert embed["description"] == "Wallet"
    assert [name for name, _ in fields(embed)] == [f"> **{n}**" for n in [
        "CURRENCIES", "DUNGEON TOKENS", "KEYS", "MAP CURRENCIES", "LIVING SEASON 3", "LIVING SEASON 4",
        "ICEBROOD SAGA", "END OF DRAGONS", "SECRETS OF THE OBSCURE", "STRIKE MISSIONS", "COMPETITION", "RAIDS",
    ]]
    assert embed["author"]["name"] == "Example.1234"
    assert [url for url, _ in requests] == [
        API + "account/wallet", API + "account/bank", API + "account/inventory",
        API + "account/materials", API + "characters?page=0&page_size=200",
    ]


async def test_overview_lines():
    embed, _ = await subject.wallet(OVERVIEW, currencies=CURRENCIES, items=ITEMS)
    # No emojis usable here, so each line starts with an empty emoji
    currencies = section(embed, "CURRENCIES")
    assert currencies[:2] == [" 123 gold 45 silver 67 copper  Coin", " 500 Gem"]
    assert " 0 Currency 2" in currencies
    assert section(embed, "RAIDS") == [" 7 Magnetite Shard", " 0 Currency 70"]
    # Items count across bank and material storage; leading counts in item
    # names are dropped
    assert section(embed, "LIVING SEASON 3")[0] == " 350 Blood Ruby"
    # The old Bandit Crest item is counted but not shown (they're a wallet
    # currency now)
    assert not any("Bandit Crest" in value for _, value in fields(embed))


async def test_overview_sometimes_jokes():
    embed, _ = await subject.wallet(OVERVIEW, currencies=CURRENCIES, items=ITEMS, random_value=0.9)
    assert "> **EXPANSION LEVEL CONTENT**" in [name for name, _ in fields(embed)]


async def test_one_currency():
    embed, requests = await subject.wallet([(200, WALLET)], currencies=CURRENCIES, items=ITEMS, currency="28")
    assert embed["title"] == "Magnetite Shard"
    assert embed["description"] == "About currency 28"
    assert embed["thumbnail"]["url"] == "https://render/currency/28.png"
    assert fields(embed) == [("Amount in wallet", "7")]
    assert requests == [(API + "account/wallet", {"access_token": "KEY"})]


async def test_coins_and_missing_currencies():
    embed, _ = await subject.wallet([(200, WALLET)], currencies=CURRENCIES, items=ITEMS, currency="1")
    assert fields(embed) == [("Amount in wallet", "123 gold 45 silver 67 copper ")]
    embed, _ = await subject.wallet([(200, WALLET)], currencies=CURRENCIES, items=ITEMS, currency="2")
    assert fields(embed) == [("Amount in wallet", "0")]


async def test_currency_by_name():
    embed, _ = await subject.wallet([(200, WALLET)], currencies=CURRENCIES, items=ITEMS, currency="magnetite")
    assert embed["title"] == "Magnetite Shard"
    embed, _ = await subject.wallet([(200, WALLET)], currencies=CURRENCIES, items=ITEMS, currency="gold")
    assert embed["title"] == "Coin"


async def test_unknown_currency_name():
    sent, requests = await subject.wallet([], currencies=CURRENCIES, items=ITEMS, currency="nothing")
    assert sent == "No results found for Nothing"
    assert requests == []
