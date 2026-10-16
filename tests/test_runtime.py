"""The bot runtime: settings and the slash command error handler."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import app_commands

from gw2bot.bot import GW2Bot
from gw2bot.config import ConfigError, Settings


def test_settings_require_token():
    with pytest.raises(ConfigError):
        Settings.from_env({})


def test_settings_defaults():
    settings = Settings.from_env({"DISCORD_TOKEN": "tok"})
    assert settings.token == "tok"
    assert settings.prefixes == (">",)
    assert settings.debug is False
    assert settings.owner_id is None
    assert settings.mongo_uri == "mongodb://localhost:27017"
    # Matches Toothy's default so existing data is found
    assert settings.mongo_db == "toothy"


def test_settings_from_env():
    settings = Settings.from_env({
        "DISCORD_TOKEN": "tok",
        "OWNER_ID": "123",
        "TEST_GUILD": "456",
        "PREFIX": "!",
        "DEBUG": "yes",
        "MONGO_HOST": "mongo",
        "MONGO_PORT": "27018",
        "MONGO_DB": "gw2",
        "LOG_DIR": "/tmp/logs",
    })
    assert settings.owner_id == 123
    assert settings.test_guild == 456
    assert settings.prefixes == ("!",)
    assert settings.debug is True
    assert settings.mongo_uri == "mongodb://mongo:27018"
    assert settings.mongo_db == "gw2"
    assert settings.log_dir == "/tmp/logs"


def test_settings_blank_values_use_defaults():
    settings = Settings.from_env({"DISCORD_TOKEN": "tok", "OWNER_ID": "", "PREFIX": " "})
    assert settings.owner_id is None
    assert settings.prefixes == (">",)


def test_settings_reject_invalid_numbers():
    with pytest.raises(ConfigError, match="OWNER_ID"):
        Settings.from_env({"DISCORD_TOKEN": "tok", "OWNER_ID": "me"})


def test_mongo_uri_with_credentials_is_escaped():
    settings = Settings.from_env({
        "DISCORD_TOKEN": "tok",
        "MONGO_USER": "bot user",
        "MONGO_PASSWORD": "p@ss:word",
        "MONGO_AUTH_DB": "gw2",
    })
    assert settings.mongo_uri == "mongodb://bot+user:p%40ss%3Aword@localhost:27017/gw2"


def test_mongo_uri_auth_db_defaults_to_admin():
    settings = Settings.from_env({"DISCORD_TOKEN": "tok", "MONGO_USER": "u", "MONGO_PASSWORD": "p"})
    assert settings.mongo_uri.endswith("@localhost:27017/admin")


def test_mongo_uri_override():
    uri = "mongodb+srv://u:p@cluster.example.net/?tls=true"
    settings = Settings.from_env({"DISCORD_TOKEN": "tok", "MONGO_URI": uri, "MONGO_HOST": "ignored"})
    assert settings.mongo_uri == uri


# --- Error handler ---------------------------------------------------------


@pytest.fixture
async def bot():
    bot = GW2Bot(Settings(token="tok"))
    yield bot
    bot.database.client.close()


def make_interaction(done=False, cog=None):
    interaction = MagicMock()
    interaction.response.is_done.return_value = done
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.command.binding = cog
    return interaction


def sent_message(interaction):
    for method in (interaction.response.send_message, interaction.followup.send):
        if method.await_count:
            assert method.await_args.kwargs == {"ephemeral": True}
            return method.await_args.args[0]
    return None


async def test_command_errors_are_delegated_to_the_cog(bot):
    cog = MagicMock()
    cog.cog_error_handler = AsyncMock(return_value="Your API key is invalid!")
    interaction = make_interaction(cog=cog)
    original = ValueError("boom")
    error = app_commands.CommandInvokeError(interaction.command, original)

    await bot.on_app_command_error(interaction, error)

    cog.cog_error_handler.assert_awaited_once_with(interaction, original)
    assert sent_message(interaction) == "Your API key is invalid!"


async def test_unhandled_command_errors_get_a_generic_message(bot):
    cog = MagicMock()
    cog.cog_error_handler = AsyncMock(return_value="")
    interaction = make_interaction(done=True, cog=cog)
    error = app_commands.CommandInvokeError(interaction.command, ValueError("boom"))

    await bot.on_app_command_error(interaction, error)

    assert sent_message(interaction).startswith("Something went wrong.")
    interaction.response.send_message.assert_not_awaited()


async def test_missing_permissions_are_listed(bot):
    interaction = make_interaction()
    error = app_commands.MissingPermissions(["manage_guild", "manage_roles"])

    await bot.on_app_command_error(interaction, error)

    assert "`Manage Server, Manage Roles`" in sent_message(interaction)


async def test_failed_checks_send_nothing(bot):
    interaction = make_interaction()

    await bot.on_app_command_error(interaction, app_commands.CheckFailure())

    assert sent_message(interaction) is None


async def test_bot_requests_the_intents_the_cog_needs(bot):
    assert bot.intents.guilds
    assert bot.intents.members
    assert bot.intents.message_content
    assert not bot.intents.presences


def test_auto_sync_setting():
    assert Settings.from_env({"DISCORD_TOKEN": "tok"}).auto_sync is True
    assert Settings.from_env({"DISCORD_TOKEN": "tok", "AUTO_SYNC": "false"}).auto_sync is False


# --- Command sync ----------------------------------------------------------


class FakeCollection:
    def __init__(self):
        self.docs = {}

    async def find_one(self, query):
        return self.docs.get(query["_id"])

    async def update_one(self, query, update, upsert=False):
        self.docs.setdefault(query["_id"], {"_id": query["_id"]}).update(update["$set"])


def add_command(bot, name, description="A command"):
    async def callback(interaction):
        pass

    bot.tree.add_command(app_commands.Command(name=name, description=description, callback=callback))


@pytest.fixture
def syncing_bot(bot):
    bot.state = FakeCollection()
    bot.tree.sync = AsyncMock()
    add_command(bot, "account")
    return bot


async def test_first_start_syncs(syncing_bot):
    assert await syncing_bot.sync_commands_if_changed() is True
    syncing_bot.tree.sync.assert_awaited_once_with()


async def test_unchanged_commands_do_not_sync(syncing_bot):
    await syncing_bot.sync_commands_if_changed()
    assert await syncing_bot.sync_commands_if_changed() is False
    assert syncing_bot.tree.sync.await_count == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda bot: add_command(bot, "wallet"),
        lambda bot: bot.tree.remove_command("account"),
        lambda bot: (bot.tree.remove_command("account"), add_command(bot, "account", "Changed"))[0],
    ],
    ids=["added", "removed", "description changed"],
)
async def test_changed_commands_sync(syncing_bot, change):
    await syncing_bot.sync_commands_if_changed()
    change(syncing_bot)
    assert await syncing_bot.sync_commands_if_changed() is True
    assert syncing_bot.tree.sync.await_count == 2


async def test_failed_sync_is_not_recorded(syncing_bot):
    syncing_bot.tree.sync.side_effect = RuntimeError("discord down")
    with pytest.raises(RuntimeError):
        await syncing_bot.sync_commands_if_changed()
    syncing_bot.tree.sync.side_effect = None
    assert await syncing_bot.sync_commands_if_changed() is True


async def test_manual_sync_is_recorded(syncing_bot):
    await syncing_bot.record_command_sync()
    assert await syncing_bot.sync_commands_if_changed() is False
    syncing_bot.tree.sync.assert_not_awaited()


def test_command_hash_ignores_registration_order():
    from gw2bot.bot import command_tree_hash

    first = GW2Bot(Settings(token="tok"))
    second = GW2Bot(Settings(token="tok"))
    for name in ("a", "b"):
        add_command(first, name)
    for name in ("b", "a"):
        add_command(second, name)
    assert command_tree_hash(first.tree) == command_tree_hash(second.tree)
