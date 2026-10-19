def test_cog_imports_and_defines_commands():
    from gw2bot.cogs.guildwars2 import GuildWars2

    # It shrinks as features move to their own cogs; the full command tree
    # is pinned by test_migrate.test_command_tree_is_unchanged
    assert GuildWars2.__cog_app_commands__
