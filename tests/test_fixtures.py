"""Run logic against recorded GW2 API responses (tests/fixtures/gw2api)."""
import importlib.util
import json

import pytest

import subject
from conftest import ROOT

FIXTURES = ROOT / "tests" / "fixtures" / "gw2api"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("skills__*.json")), ids=lambda p: p.stem)
def test_recorded_skills_format(path):
    skill = json.loads(path.read_text(encoding="utf-8"))
    fields = subject.skill_fields(skill)
    assert len(fields) == len(skill.get("facts", []))


def test_recorded_item_rarities_are_known(gamedata):
    items = [load("items__46762.json")] + load("items__ids-19721_24575_24615_30684.json")
    for item in items:
        assert item["rarity"] in gamedata["items"]["rarity_colors"]


def test_recorded_world_populations_are_known():
    for world in load("worlds__ids-all.json"):
        assert 0 <= subject.population_to_int(world["population"]) <= 4


@pytest.fixture
def recorder():
    path = ROOT / "scripts" / "record_gw2_fixtures.py"
    spec = importlib.util.spec_from_file_location("record_gw2_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REAL_ACCOUNT = {
    "id": "real-id",
    "name": "Real.5678",
    "guilds": ["g1", "g2"],
    "guild_leader": ["g2"],
    "world": 2003,
    "created": "2012-11-17T16:38:00Z",
    "age": 1000000,
    "wvw_rank": 82,
    "fractal_level": 100,
    "daily_ap": 8000,
    "commander": True,
}


@pytest.fixture
def scrubber(recorder):
    import copy
    import random

    return recorder.Scrubber(
        copy.deepcopy(REAL_ACCOUNT),
        ["Real Name", "Other Name", "Alt"],
        world_ids=[1001, 2003, 2101],
        rng=random.Random(0),
    )


def test_recorder_scrubs_account(recorder, scrubber):
    import copy

    account = scrubber.scrub("account", copy.deepcopy(REAL_ACCOUNT))
    text = json.dumps(account)
    scrubber.check("account", text)
    assert account["name"] == "Example.1234"
    assert account["created"] != REAL_ACCOUNT["created"]
    # The same guild maps to the same placeholder everywhere
    assert account["guild_leader"] == [account["guilds"][1]]
    assert account["world"] // 1000 == 2
    assert account["commander"] is True
    assert 0 <= account["fractal_level"] <= 100


def test_recorder_scrubs_characters(scrubber):
    characters = scrubber.scrub(
        "characters?ids=all",
        [
            {
                "name": "Real Name",
                "guild": "g1",
                "deaths": 100,
                "equipment": [{"id": 1, "bound_to": "Real Name"}],
                "bags": [{"inventory": [{"id": 2, "bound_to": "Alt"}, None]}],
            },
            {"name": "Other Name"},
        ],
    )
    scrubber.check("characters", json.dumps(characters))
    assert [c["name"] for c in characters] == ["Character 1", "Character 2"]
    assert characters[0]["equipment"][0]["bound_to"] == "Character 1"
    assert characters[0]["bags"][0]["inventory"][0]["bound_to"] == "Character 3"
    assert 70 <= characters[0]["deaths"] <= 130


def test_recorder_jitters_wallet_and_pvp(scrubber):
    wallet = scrubber.scrub("account/wallet", [{"id": 1, "value": 1000}, {"id": 2, "value": 0}])
    assert 700 <= wallet[0]["value"] <= 1300 and wallet[0]["value"] != 1000
    assert wallet[1]["value"] == 0
    stats = scrubber.scrub("pvp/stats", {"pvp_rank": 80, "aggregate": {"wins": 500, "losses": 400}})
    assert 1 <= stats["pvp_rank"] <= 80
    assert stats["aggregate"] != {"wins": 500, "losses": 400}


def test_recorder_refuses_to_write_leaks(recorder, scrubber):
    with pytest.raises(recorder.LeakError):
        scrubber.check("characters", json.dumps({"note": "bound to Other Name"}))
