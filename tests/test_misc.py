"""/wiki and /chatcode."""
import pytest

import subject

EN_SEARCH = "https://wiki.guildwars2.com/index.php?title=Special%3ASearch&search="


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


def results_page(*titles):
    """A wiki search results page."""
    headings = "".join(
        f'<div class="mw-search-result-heading"><a href="/wiki/{t.replace(" ", "_")}" title="{t}">{t}</a></div>'
        for t in titles
    )
    return f"<html><body>{headings}</body></html>"


# --- /wiki -----------------------------------------------------------------------------


async def test_wiki_search_results():
    url = EN_SEARCH + "Arch"
    titles = ["Lion's Arch", "Arch of the Jade Sea", "Arches", "Arch (disambiguation)", "Arcade", "Six"]
    session = subject.FakeWikiSession({url: results_page(*titles)})
    embed, requests = await subject.wiki(session, search_text="Arch")
    assert embed["title"] == "Wiki search results"
    assert embed["description"] == "Closest matches"
    # The first five, with closing parentheses escaped for the link
    assert fields(embed) == [
        ("Lion's Arch", "[Click here](https://wiki.guildwars2.com/wiki/Lion's_Arch)"),
        ("Arch of the Jade Sea", "[Click here](https://wiki.guildwars2.com/wiki/Arch_of_the_Jade_Sea)"),
        ("Arches", "[Click here](https://wiki.guildwars2.com/wiki/Arches)"),
        ("Arch (disambiguation)", "[Click here](https://wiki.guildwars2.com/wiki/Arch_(disambiguation\\))"),
        ("Arcade", "[Click here](https://wiki.guildwars2.com/wiki/Arcade)"),
    ]
    assert requests == [(url, {"User-Agent": "TybaltBot/v2"})]


async def test_wiki_exact_match():
    url = EN_SEARCH + "Divinity's Reach"
    page = "https://wiki.guildwars2.com/wiki/Divinity%27s_Reach"
    session = subject.FakeWikiSession(
        {page: "<html><head><title>Divinity's Reach - Guild Wars 2 Wiki (GW2W)</title></head></html>"},
        redirects={url: page},
    )
    embed, _ = await subject.wiki(session, search_text="Divinity's Reach")
    assert embed["title"] == "Divinity's Reach - Guild Wars 2 Wiki (GW2W)"
    assert embed["url"] == page


@pytest.mark.parametrize(
    "language, url",
    [
        ("de", "https://wiki-de.guildwars2.com/index.php?search=Arch&title=Spezial%3ASuche&"),
        ("fr", "https://wiki-fr.guildwars2.com/index.php?search=Arch&title=Spécial%3ARecherche"),
        ("es", "https://wiki-es.guildwars2.com/index.php?title=Especial%3ABuscar&search=Arch"),
    ],
)
async def test_wiki_languages(language, url):
    session = subject.FakeWikiSession({url: results_page("Arch")})
    embed, requests = await subject.wiki(session, search_text="Arch", language=language)
    base = url.split("/index.php")[0]
    assert fields(embed) == [("Arch", f"[Click here]({base}/wiki/Arch)")]
    assert [u for u, _ in requests] == [url]


async def test_wiki_no_results():
    session = subject.FakeWikiSession({EN_SEARCH + "zzz": results_page()})
    sent, _ = await subject.wiki(session, search_text="zzz")
    assert sent == "No results for your search"


async def test_wiki_search_too_long():
    session = subject.FakeWikiSession()
    sent, requests = await subject.wiki(session, search_text="a" * 301)
    assert sent == "Search too long"
    assert requests == []


# --- /chatcode ----------------------------------------------------------------------------


def reply(code):
    return f"Here's your chatcode. No refunds. ```\n{code}```"


async def test_chatcode():
    assert await subject.chatcode(item="46762", quantity=1) == reply("[&AgGqtgAA]")
    assert await subject.chatcode(item="46762", quantity=1, skin="3709", upgrade_1="24575", upgrade_2="24615") == (
        reply("[&AgGqtgDgfQ4AAP9fAAAnYAAA]")
    )


async def test_chatcode_second_upgrade_only_fills_the_first_slot():
    assert await subject.chatcode(item="46762", quantity=1, upgrade_2="24575") == reply("[&AgGqtgBA/18AAA==]")


@pytest.mark.parametrize("quantity", [0, 256])
async def test_chatcode_quantity_range(quantity):
    assert await subject.chatcode(item="46762", quantity=quantity) == (
        "Invalid quantity. Quantity can be a number between 1 and 255"
    )


async def test_chatcode_autocompletes():
    items = [
        {"_id": 19721, "name": "Glob of Ectoplasm", "type": "CraftingMaterial"},
        {"_id": 24575, "name": "Superior Rune of Ectoplasm", "type": "UpgradeComponent"},
    ]
    skins = [{"_id": 3709, "name": "Ectoplasmic Greatsword Skin"}]
    assert await subject.chatcode_choices("item", "ecto", items=items) == [
        ("Glob of Ectoplasm", "19721"), ("Superior Rune of Ectoplasm", "24575"),
    ]
    assert await subject.chatcode_choices("upgrade", "ecto", items=items) == [("Superior Rune of Ectoplasm", "24575")]
    assert await subject.chatcode_choices("skin", "ecto", skins=skins) == [("Ectoplasmic Greatsword Skin", "3709")]
    assert await subject.chatcode_choices("item", "", items=items) == []


# --- Known bugs ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="the search text isn't URL-encoded")
async def test_wiki_search_text_is_encoded():
    url = EN_SEARCH + "Rune%20%26%20Sigil%20%2B1%20%23"
    session = subject.FakeWikiSession({url: results_page("Rune")})
    embed, requests = await subject.wiki(session, search_text="Rune & Sigil +1 #")
    assert [u for u, _ in requests] == [url]


@pytest.mark.xfail(strict=True, reason="typed names aren't looked up")
async def test_chatcode_with_typed_names():
    # Like other commands, typing a name instead of picking it uses the first match
    items = [{"_id": 46762, "name": "Banana", "type": "Consumable"},
             {"_id": 24575, "name": "Superior Rune of Bananas", "type": "UpgradeComponent"}]
    skins = [{"_id": 3709, "name": "Banana Skin"}]
    sent = await subject.chatcode(item="banana", quantity=1, skin="banana skin", upgrade_1="rune of bananas",
                                  items=items, skins=skins)
    assert sent == reply("[&AgGqtgDAfQ4AAP9fAAA=]")
    assert await subject.chatcode(item="Anvil", quantity=1, items=items) == "Could not find any items named Anvil"
