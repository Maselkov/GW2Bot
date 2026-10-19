"""/wvw info."""
import pytest

import subject

API = "https://api.guildwars2.com/v2/"


def objective(owner, points):
    return {"owner": owner, "points_tick": points}


def match(*, red=(11001, 1001), green=(11002,), blue=(11003, 1003), kills=None, deaths=None):
    """Synthetic /v2/wvw/matches (worlds below 10000 are pre-restructuring ids)."""
    return {
        "all_worlds": {"red": list(red), "green": list(green), "blue": list(blue)},
        "scores": {"red": 120000, "green": 98000, "blue": 101000},
        "victory_points": {"red": 210, "green": 180, "blue": 195},
        "kills": kills or {"red": 5000, "green": 4000, "blue": 4500},
        "deaths": deaths or {"red": 4000, "green": 4600, "blue": 4900},
        "maps": [
            {"objectives": [objective("Red", 5), objective("Green", 2), objective("Neutral", 0)]},
            {"objectives": [objective("Red", 10), objective("Blue", 5)]},
        ],
    }


def fields(embed):
    return [(f["name"], f["value"]) for f in embed["fields"]]


async def test_info_for_own_team():
    responses = [(200, {"name": "Example.1234", "wvw": {"team_id": 11001, "rank": 10}}), (200, match())]
    embed, requests = await subject.wvw_info(responses)
    assert embed["author"]["name"] == "Moogooloo"
    assert embed["description"] == "Performance"
    assert embed["color"] == 0xE74C3C  # red
    assert fields(embed) == [
        ("Score", "120000"),
        ("Points per tick", "15"),
        ("Victory Points", "210"),
        ("K/D ratio", "1.25"),
        ("Matchup", "Red: Moogooloo\nBlue: Domain of Torment\nGreen: Rall's Rest"),
    ]
    assert requests == [
        (API + "account", {"access_token": "KEY"}),
        (API + "wvw/matches?world=11001", {}),
    ]


@pytest.mark.parametrize("team", ["11002", "rall's rest"])
async def test_info_for_another_team(team):
    embed, requests = await subject.wvw_info([(200, match())], team=team)
    assert embed["author"]["name"] == "Rall's Rest"
    assert embed["color"] == 0x2ECC71  # green
    assert fields(embed)[1] == ("Points per tick", "2")
    # No key needed
    assert requests == [(API + "wvw/matches?world=11002", {})]


async def test_blue_team_and_no_deaths():
    deaths = {"red": 1, "green": 1, "blue": 0}
    embed, _ = await subject.wvw_info([(200, match(deaths=deaths))], team="11003")
    assert embed["color"] == 0x3498DB  # blue
    assert ("K/D ratio", "4500.0") in fields(embed)


async def test_unknown_team_name():
    sent, requests = await subject.wvw_info([], team="Anvil Rock")
    assert sent == "Invalid team name"
    assert requests == []


async def test_account_without_team():
    sent, _ = await subject.wvw_info([(200, {"name": "Example.1234", "wvw": {"rank": 10}})])
    assert sent.startswith("Your account isn't on a WvW team right now.")


async def test_team_not_in_the_match():
    sent, _ = await subject.wvw_info([(200, match(green=(11005,)))], team="11002")
    assert sent == "That team isn't in a match right now."


async def test_empty_side_shows_a_dash():
    embed, _ = await subject.wvw_info([(200, match(green=(2001,)))], team="11001")
    assert fields(embed)[-1] == ("Matchup", "Red: Moogooloo\nBlue: Domain of Torment\nGreen: -")


async def test_own_team_needs_account_permission():
    from gw2bot.gw2api.errors import APIKeyError

    with pytest.raises(APIKeyError):
        await subject.wvw_info([], permissions=["pvp"])
