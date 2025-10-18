from discord import app_commands

# Shared group for all character-related slash commands
group = app_commands.Group(name="character", description="Character related commands")

__all__ = ["group"]
