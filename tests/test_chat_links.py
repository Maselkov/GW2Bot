"""Chat link previews: posting a [&...] link shows what it is."""
import pytest

import subject

WIKI = "https://wiki.guildwars2.com/wiki/"
OPT_OUT = 'Server admins can opt out of chat link previewing by using the "/server preview_chat_links" command'

# Cached game data
TWILIGHT = {"_id": 46762, "name": "Twilight", "icon": "https://render/twilight.png", "rarity": "Legendary",
            "details": {}}
ECTO = {"_id": 19721, "name": "Glob of Ectoplasm", "icon": "https://render/ecto.png", "rarity": "Exotic",
        "details": {}}
FORCE = {"_id": 24615, "name": "Superior Sigil of Force", "icon": "https://render/force.png", "rarity": "Exotic",
         "details": {"suffix": "of Force"}}
DUSK = {"_id": 3709, "name": "Dusk", "icon": "https://render/dusk.png"}
OUTFIT = {"_id": 15, "name": "Ghostly Outfit", "icon": "https://render/ghostly.png"}
WAYPOINT = {"_id": 1234, "type": "waypoint", "name": "Lion's Arch Waypoint"}
RECIPE = {"_id": 7, "output_item_id": 46762, "output_item_count": 1, "disciplines": ["Weaponsmith"],
          "ingredients": [{"item_id": 19721, "count": 250}]}
SKILL = {"_id": 5501, "name": "Meteor Shower", "icon": "https://render/meteor.png", "slot": "Weapon_5",
         "weapon_type": "Staff", "professions": ["Elementalist"], "description": "Call down meteors."}
TRAIT = {"_id": 1503, "name": "Fresh Air", "icon": "https://render/fresh_air.png",
         "description": "Air attunement recharges faster."}


def cache():
    return subject.gw2_db(items=[TWILIGHT, ECTO, FORCE], skins=[DUSK], outfits=[OUTFIT], pois=[WAYPOINT],
                          recipes=[RECIPE], skills=[SKILL], traits=[TRAIT])


def fields(embed):
    return [(f["name"], f["value"]) for f in embed.get("fields", [])]


async def preview(content, **options):
    [(embed, replied)], counted = await subject.post_chat_link(content, db=cache(), **options)
    assert replied
    return embed, counted


# --- Each kind of link -------------------------------------------------------------------


async def test_item_with_skin_and_upgrade(gamedata):
    link = subject.chat_code(46762, 1, 3709, [24615])
    embed, counted = await preview(f"Look at my {link}!", pages=[WIKI + "Twilight"])
    assert embed["title"] == "Twilight of Force"
    assert embed["url"] == WIKI + "Twilight"
    assert embed["color"] == int(gamedata["items"]["rarity_colors"]["Legendary"], 16)
    # The skin's icon
    assert embed["thumbnail"]["url"] == "https://render/dusk.png"
    assert fields(embed) == [("Skin", "Dusk"), ("Upgrade", "Superior Sigil of Force")]
    assert embed["description"] == "Chat link preview"
    assert embed["author"] == {"name": "Example", "icon_url": "https://cdn/example.png"}
    assert embed["footer"] == {"text": OPT_OUT, "icon_url": "https://cdn/bot.png"}
    assert counted == [{"item": 1}]


async def test_item_stack():
    embed, _ = await preview(subject.chat_code(19721, 250))
    assert embed["title"] == "250 Glob of Ectoplasm"
    assert embed["thumbnail"]["url"] == "https://render/ecto.png"
    assert "url" not in embed


async def test_map_link():
    embed, counted = await preview(subject.link(4, 1234))
    assert embed["title"] == "Map link"
    assert fields(embed) == [("Waypoint", "Lion's Arch Waypoint")]
    assert counted == [{"map_link": 1}]


async def test_skill_and_trait():
    embed, _ = await preview(subject.link(6, 5501))
    assert embed["title"] == "Meteor Shower"
    assert embed["footer"] == {"text": OPT_OUT, "icon_url": "https://cdn/bot.png"}
    embed, counted = await preview(subject.link(7, 1503))
    assert embed["title"] == "Fresh Air"
    assert counted == [{"trait": 1}]


async def test_recipe():
    embed, _ = await preview(subject.link(9, 7))
    assert embed["title"] == "Recipe: 1 Twilight"
    assert fields(embed) == [("Crafting disciplines", "Weaponsmith"), ("Ingredients", "250 Glob of Ectoplasm")]


async def test_wardrobe_and_outfit():
    embed, _ = await preview(subject.link(10, 3709))
    assert (embed["title"], embed["thumbnail"]["url"]) == ("Dusk", "https://render/dusk.png")
    embed, _ = await preview(subject.link(11, 15))
    assert (embed["title"], embed["thumbnail"]["url"]) == ("Ghostly Outfit", "https://render/ghostly.png")


async def test_in_dms():
    embed, _ = await preview(subject.chat_code(19721, 1), in_guild=False)
    assert embed["footer"] == {"icon_url": "https://cdn/bot.png"}


# --- No preview ---------------------------------------------------------------------------


async def test_coin_links_are_counted_but_not_shown():
    sent, counted = await subject.post_chat_link(subject.link(1, 100), db=cache())
    assert sent == []
    assert counted == [{"coin": 1}]


@pytest.mark.parametrize("options", [{"opted_out": True}, {"author_is_bot": True}])
async def test_opted_out_servers_and_bots(options):
    sent, counted = await subject.post_chat_link(subject.chat_code(19721, 1), db=cache(), **options)
    assert sent == counted == []


async def test_messages_without_links():
    assert await subject.post_chat_link("Just chatting [about] things", db=cache()) == ([], [])


async def test_uncached_items_and_skills_show_nothing():
    for content in subject.chat_code(1, 1), subject.link(6, 1):
        sent, _ = await subject.post_chat_link(content, db=cache())
        assert sent == []


# --- Fixes ----------------------------------------------------------------------------------


@pytest.mark.parametrize("content", ["[&!!]", subject.link(30, 1)], ids=["undecodable", "unknown-type"])
async def test_invalid_links(content):
    assert await subject.post_chat_link(content, db=cache()) == ([], [])


async def test_item_with_an_uncached_skin():
    embed, _ = await preview(subject.chat_code(46762, 1, 1, []))
    assert embed["title"] == "Twilight"
    assert fields(embed) == [("Skin", "Unknown")]
    assert embed["thumbnail"]["url"] == "https://render/twilight.png"


async def test_uncached_point_of_interest(caplog):
    sent, counted = await subject.post_chat_link(subject.link(4, 9999), db=cache())
    assert sent == []
    assert counted == [{"map_link": 1}]
    assert "Exception previewing a chat link" in caplog.text


async def test_item_whose_first_upgrade_is_uncached():
    # The second upgrade is read after the first one's id, known or not
    embed, _ = await preview(subject.chat_code(46762, 1, None, [1, 24615]))
    assert fields(embed) == [("Upgrades", "Unknown upgrade\nSuperior Sigil of Force")]
    assert embed["title"] == "Twilight of Force"
