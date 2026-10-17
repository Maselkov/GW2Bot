def test_cog_imports_and_defines_commands():
    from gw2bot.cogs.guildwars2 import GuildWars2

    commands = GuildWars2.__cog_app_commands__
    assert len(commands) > 10
