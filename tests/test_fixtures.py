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


@pytest.fixture
def recorder():
    path = ROOT / "scripts" / "record_gw2_fixtures.py"
    spec = importlib.util.spec_from_file_location("record_gw2_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_public_endpoints_are_recorded(recorder):
    # The repository is public: account data must never be committed. Tests
    # needing it use synthetic data instead.
    recorded = {path.name for path in FIXTURES.glob("*.json")}
    public = {recorder.fixture_name(endpoint) for endpoint in recorder.ENDPOINTS}
    assert recorded <= public, f"not from a public endpoint: {sorted(recorded - public)}"


def test_recorded_wvw_match_summary():
    match = load("wvw__matches__world-11001.json")
    summary = subject.wvw_match_summary(match, 11001)
    assert summary["color"] == "green"
    assert summary["score"] == match["scores"]["green"]
    assert summary["kills"] == match["kills"]["green"]
    assert 0 < summary["points_per_tick"]
    # Only the teams, not the world ids from before the restructuring
    assert summary["teams"] == {"red": [11011], "blue": [11007], "green": [11001]}


def test_recorded_wvw_match_without_the_team():
    match = load("wvw__matches__world-11001.json")
    assert subject.wvw_match_summary(match, 11002) is None
    # A legacy world id isn't a team
    assert subject.wvw_match_summary(match, 1) is None
