"""/wiki and /chatcode."""
import discord
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
    url = EN_SEARCH + "Divinity%27s%20Reach"
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


DE_SEARCH = "https://wiki-de.guildwars2.com/index.php?search=Arch&title=Spezial%3ASuche&"


async def test_wiki_searches_the_wiki_in_the_users_discord_language():
    session = subject.FakeWikiSession({DE_SEARCH: results_page("Arch")})
    _, requests = await subject.wiki(session, search_text="Arch", locale=discord.Locale.german)
    assert [u for u, _ in requests] == [DE_SEARCH]


async def test_wiki_language_setting_beats_the_discord_language():
    session = subject.FakeWikiSession({DE_SEARCH: results_page("Arch")})
    _, requests = await subject.wiki(session, search_text="Arch", locale=discord.Locale.french,
                                     users=subject.FakeUserRepo({"language": "de"}))
    assert [u for u, _ in requests] == [DE_SEARCH]


async def test_wiki_in_a_language_the_bot_doesnt_speak_searches_in_english():
    session = subject.FakeWikiSession({EN_SEARCH + "Arch": results_page("Arch")})
    _, requests = await subject.wiki(session, search_text="Arch", locale=discord.Locale.japanese)
    assert [u for u, _ in requests] == [EN_SEARCH + "Arch"]


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


ECTO_DE = {"_id": 19721, "name": "Glob of Ectoplasm", "type": "CraftingMaterial",
           "l10n": {"de": {"name": "Ektoplasmakugel"}}}
# German name starting like the English one does
GLOBE_DE = {"_id": 5, "name": "Globe", "type": "Trophy", "l10n": {"de": {"name": "Globus"}}}


async def test_autocomplete_finds_and_shows_items_by_their_name_in_the_users_language():
    choices = await subject.chatcode_choices("item", "ekto", items=[ECTO_DE], locale=discord.Locale.german)
    assert choices == [("Ektoplasmakugel", "19721")]


async def test_autocomplete_finds_items_by_their_english_name_too():
    choices = await subject.chatcode_choices("item", "glob of", items=[ECTO_DE], locale=discord.Locale.german)
    assert choices == [("Ektoplasmakugel", "19721")]


async def test_autocomplete_lists_matches_in_the_users_language_first():
    choices = await subject.chatcode_choices("item", "glob", items=[ECTO_DE, GLOBE_DE], locale=discord.Locale.german)
    assert choices == [("Globus", "5"), ("Ektoplasmakugel", "19721")]


async def test_autocomplete_in_english_ignores_translations():
    choices = await subject.chatcode_choices("item", "ekto", items=[ECTO_DE])
    assert choices == []


async def test_autocomplete_falls_back_to_english_names_without_a_translation():
    skin = {"_id": 3709, "name": "Ectoplasmic Greatsword Skin"}
    choices = await subject.chatcode_choices("skin", "ecto", skins=[skin], locale=discord.Locale.french)
    assert choices == [("Ectoplasmic Greatsword Skin", "3709")]


# --- Wiki links ---------------------------------------------------------------------------

DE_BANANA = "https://wiki-de.guildwars2.com/wiki/Banane"
EN_BANANA = "https://wiki.guildwars2.com/wiki/Banana"


async def test_wiki_links_go_to_the_page_in_the_users_language():
    url, _ = await subject.wiki_page("Banane", "de", "Banana", pages=[DE_BANANA, EN_BANANA])
    assert url == DE_BANANA


async def test_wiki_links_go_to_the_english_page_when_the_language_wiki_has_none():
    url, checked = await subject.wiki_page("Banane", "de", "Banana", pages=[EN_BANANA])
    assert url == EN_BANANA
    assert checked == [DE_BANANA, EN_BANANA]


async def test_no_wiki_link_without_a_page():
    url, _ = await subject.wiki_page("Banane", "de", "Banana")
    assert url is None


async def test_no_wiki_link_when_the_wiki_cant_be_reached():
    url, checked = await subject.wiki_page("Banane", "de", "Banana", head_error=TimeoutError())
    assert url is None
    # Not tried again on the English wiki: it's the same servers
    assert checked == [DE_BANANA]


# --- Fixes --------------------------------------------------------------------------------


async def test_wiki_search_text_is_encoded():
    url = EN_SEARCH + "Rune%20%26%20Sigil%20%2B1%20%23"
    session = subject.FakeWikiSession({url: results_page("Rune")})
    embed, requests = await subject.wiki(session, search_text="Rune & Sigil +1 #")
    assert [u for u, _ in requests] == [url]


async def test_chatcode_with_typed_names():
    # Like other commands, typing a name instead of picking it uses the first match
    items = [{"_id": 46762, "name": "Banana", "type": "Consumable"},
             {"_id": 24575, "name": "Superior Rune of Bananas", "type": "UpgradeComponent"}]
    skins = [{"_id": 3709, "name": "Banana Skin"}]
    sent = await subject.chatcode(item="banana", quantity=1, skin="banana skin", upgrade_1="rune of bananas",
                                  items=items, skins=skins)
    assert sent == reply("[&AgGqtgDAfQ4AAP9fAAA=]")
    assert await subject.chatcode(item="Anvil", quantity=1, items=items) == "Could not find any items named Anvil"
