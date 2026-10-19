"""/pvp stats and /pvp professions."""
import pytest

import subject

API = "https://api.guildwars2.com/v2/"


def games(wins, losses, desertions=0, byes=0, forfeits=0):
    return {"wins": wins, "losses": losses, "desertions": desertions, "byes": byes, "forfeits": forfeits}


# Synthetic /v2/pvp/stats (never real account data)
STATS = {
    "pvp_rank": 65,
    "pvp_rank_points": 1234,
    "pvp_rank_rollovers": 3,
    "aggregate": games(120, 80, desertions=2, byes=5, forfeits=1),
    "professions": {
        "guardian": games(50, 30, byes=2),
        "necromancer": games(20, 40),
        "mesmer": games(5, 1),
    },
    "ladders": {"ranked": games(40, 30, byes=2), "unranked": games(80, 50)},
}


def fields(embed):
    return {f["name"]: f["value"] for f in embed["fields"]}


async def test_stats(gamedata):
    embed, requests = await subject.pvp("stats", STATS)
    assert fields(embed) == {
        "Rank": "68",  # rank plus rollovers
        "Total games played": "208",
        "Total wins": "125",  # wins plus byes
        "Total winratio": "60%",
        "Ranked games played": "72",
        "Ranked wins": "42",
        "Ranked winratio": "58%",
    }
    assert embed["author"]["name"] == "Example.1234"
    assert embed["thumbnail"]["url"] == "https://render/rank.png"
    assert embed["color"] == 0xC12D2B
    # Rank 65 is in the 7th rank band (60-69)
    assert [url for url, _ in requests] == [API + "pvp/stats", API + "pvp/ranks/7"]
    assert requests[0][1] == {"access_token": "KEY"}


async def test_stats_without_games():
    stats = {**STATS, "aggregate": games(0, 0), "ladders": {"ranked": games(0, 0)}}
    embed, _ = await subject.pvp("stats", stats)
    assert fields(embed)["Total winratio"] == "0%"
    assert fields(embed)["Ranked winratio"] == "0%"


async def test_professions_overview(gamedata):
    embed, requests = await subject.pvp("professions", STATS)
    assert embed["description"] == "Professions"
    assert fields(embed) == {
        "Most played profession": "Guardian, with 82",
        "Highest winrate profession": "Mesmer, with 83%",
        "Least played profession": "Mesmer, with 6",
        "Lowest winrate profession": "Necromancer, with 33%",
    }
    assert embed["thumbnail"]["url"] == gamedata["professions"]["guardian"]["icon"]
    assert embed["author"]["name"] == "Example.1234"
    assert [url for url, _ in requests] == [API + "pvp/stats"]


async def test_single_profession(gamedata):
    embed, _ = await subject.pvp("professions", STATS, profession="guardian")
    assert embed["description"] == "Stats for guardian"
    assert fields(embed) == {"Total games played": "82", "Wins": "52", "Winratio": "63%"}
    assert embed["color"] == int(gamedata["professions"]["guardian"]["color"], 0)
    assert embed["thumbnail"]["url"] == gamedata["professions"]["guardian"]["icon"]


async def test_key_needs_pvp_permission():
    from gw2bot.gw2api.errors import APIKeyError

    with pytest.raises(APIKeyError, match="`pvp`"):
        await subject.pvp("stats", STATS, permissions=["account"])
