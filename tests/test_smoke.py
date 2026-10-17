import datetime

import pytest

import subject


def test_cog_imports_and_defines_commands():
    from gw2bot.cogs.guildwars2 import GuildWars2

    commands = GuildWars2.__cog_app_commands__
    assert len(commands) > 10


@pytest.mark.xfail(
    strict=True,
    reason="generate_population_graph uses ax.grid(b=...) and Tick.label, "
    "both removed from current matplotlib",
)
def test_population_graph_renders_png():
    start = datetime.datetime(2024, 3, 1)
    points = [(start + datetime.timedelta(days=i), i % 5) for i in range(10)]
    assert subject.population_graph(points).startswith(b"\x89PNG")
