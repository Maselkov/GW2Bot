"""/skill and /trait."""
import pytest

import subject

WIKI = "https://wiki.guildwars2.com/wiki/"

# Cached skill and trait documents (public game data)
METEOR_SHOWER = {
    "_id": 5501, "name": "Meteor Shower", "icon": "https://render/meteor.png",
    "description": "Call down meteors. <c=@reminder>Deals ConditionDamage.</c>",
    "slot": "Weapon_5", "weapon_type": "Staff", "professions": ["Elementalist"],
    "facts": [
        {"type": "Damage", "text": "Damage", "hit_count": 24, "dmg_multiplier": 1.0},
        {"type": "Recharge", "text": "Recharge", "value": 30},
    ],
}
EVISCERATE = {
    "_id": 14402, "name": "Eviscerate", "icon": "https://render/eviscerate.png",
    "slot": "Profession_1", "professions": ["Warrior"], "cost": 10,
    "facts": [{"type": "Recharge", "text": "Recharge", "value": 10}],
}
SIGNET = {
    "_id": 9000, "name": "Signet of Something", "slot": "Utility", "professions": [],
    "description": "A shared skill.",
}
TRANSFORM = {"_id": 9001, "name": "Meteor Bundle Skill", "slot": "Weapon_1", "professions": None}
SKILLS = [METEOR_SHOWER, EVISCERATE, SIGNET, TRANSFORM]

FRESH_AIR = {
    "_id": 1503, "name": "Fresh Air", "icon": "https://render/fresh_air.png",
    "description": "Air attunement recharges faster.", "specialization": 41,
    "facts": [{"type": "Recharge", "text": "Recharge", "value": 0}],
}
TRAITS = [FRESH_AIR]


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


async def test_skill(gamedata):
    embed, heads = await subject.skill_command(
        "skill", skills=SKILLS, pages=[WIKI + "Meteor_Shower"], skill="5501"
    )
    assert embed["title"] == "Meteor Shower"
    assert embed["url"] == WIKI + "Meteor_Shower"
    # Tags stripped, attributes under their in-game names
    assert embed["description"] == "Call down meteors. Deals Condition Damage."
    assert embed["thumbnail"]["url"] == "https://render/meteor.png"
    assert embed["color"] == int(gamedata["professions"]["elementalist"]["color"], 16)
    assert embed["footer"] == {
        "text": "Elementalist Staff skill 5",
        "icon_url": subject.profession_icon("Elementalist"),
    }
    # 24 hits of round(1048 * 1000 / 2597)
    assert fields(embed) == [("Tooltip", "Recharge: 30s\nDamage (24x): 9696 (24.0)")]
    assert heads == [WIKI + "Meteor_Shower"]


async def test_skill_by_typed_name():
    embed, _ = await subject.skill_command("skill", skills=SKILLS, skill="meteor")
    assert embed["title"] == "Meteor Shower"
    # No wiki page, no link
    assert "url" not in embed


async def test_profession_resource_cost():
    embed, _ = await subject.skill_command("skill", skills=SKILLS, skill="14402")
    assert embed["footer"]["text"] == "Warrior Profession Skill 1"
    assert fields(embed) == [("Tooltip", "Recharge: 10s\nAdrenaline cost: 10")]


async def test_skill_without_a_single_profession():
    embed, _ = await subject.skill_command("skill", skills=SKILLS, skill="9000")
    assert embed["description"] == "A shared skill."
    assert embed["color"] == 0xC12D2B
    assert "footer" not in embed
    assert "fields" not in embed


async def test_trait():
    embed, heads = await subject.skill_command("trait", traits=TRAITS, pages=[WIKI + "Fresh_Air"], trait="fresh")
    assert embed["title"] == "Fresh Air"
    assert embed["url"] == WIKI + "Fresh_Air"
    assert embed["description"] == "Air attunement recharges faster."
    assert fields(embed) == [("Tooltip", "Recharge: 0s")]
    assert heads == [WIKI + "Fresh_Air"]


async def test_trait_not_found():
    sent, heads = await subject.skill_command("trait", traits=TRAITS, trait="Anvil")
    assert sent == "Could not find any traits with that name."
    assert heads == []


# --- Autocomplete ------------------------------------------------------------


async def test_skill_autocomplete_leaves_out_skills_without_professions():
    choices = await subject.skill_search("skill", "meteor", skills=SKILLS)
    assert choices == [("Meteor Shower", "5501")]
    assert await subject.skill_search("skill", "", skills=SKILLS) == []
    # An empty list still counts as having professions
    assert await subject.skill_search("skill", "signet", skills=SKILLS) == [("Signet of Something", "9000")]


async def test_trait_autocomplete():
    assert await subject.skill_search("trait", "AIR", traits=TRAITS) == [("Fresh Air", "1503")]
    assert await subject.skill_search("trait", "", traits=TRAITS) == []


# --- Not found ---------------------------------------------------------------


async def test_skill_not_found():
    sent, heads = await subject.skill_command("skill", skills=SKILLS, skill="Anvil")
    assert sent == "Could not find any skills with that name."
    assert heads == []


@pytest.mark.parametrize("command", ["skill", "trait"])
async def test_unknown_id(command):
    sent, _ = await subject.skill_command(command, skills=SKILLS, traits=TRAITS, **{command: "123456"})
    assert sent == f"Could not find any {command}s with that name."


# --- The wiki ----------------------------------------------------------------


@pytest.mark.parametrize("error", ["timeout", "connection"])
async def test_skill_without_the_wiki(error):
    embed, heads = await subject.skill_command("skill", skills=SKILLS, wiki_error=error, skill="5501")
    assert embed["title"] == "Meteor Shower"
    assert "url" not in embed
    assert heads == [WIKI + "Meteor_Shower"]
