"""Services shared by the cogs: users' keys, emojis and error messages."""
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import subject
from gw2bot.emojis import Emojis
from gw2bot.errors import error_message
from gw2bot.gw2api.errors import (
    APIConnectionError,
    APIError,
    APIInactiveError,
    APIInvalidKey,
    APIKeyError,
    APINotFound,
)
from gw2bot.keys import ApiKeys

# --- Keys --------------------------------------------------------------------


def stored(permissions=("account", "pvp")):
    key = {"key": "K", "account_name": "A.1", "permissions": list(permissions)}
    return {"key": key, "keys": [key]}


def user(user_id=1):
    obj = MagicMock(id=user_id)
    obj.mention = f"<@{user_id}>"
    return obj


async def test_key_lookup():
    keys = ApiKeys(subject.FakeUserRepo(stored()))
    assert (await keys.get(user(), ["pvp"]))["key"] == "K"


@pytest.mark.parametrize("doc", [{}, {"key": None}, {"key": {}}])
async def test_missing_key(doc):
    keys = ApiKeys(subject.FakeUserRepo(doc))
    with pytest.raises(APIKeyError, match="No API key associated with your account"):
        await keys.get(user())


async def test_missing_permissions_are_listed():
    keys = ApiKeys(subject.FakeUserRepo(stored(permissions=["account"])))
    with pytest.raises(APIKeyError) as caught:
        await keys.get(user(7), ["account", "pvp", "wallet"])
    assert str(caught.value).startswith("<@7>, your API key is missing the following permissions")
    assert "`pvp, wallet`" in str(caught.value)


# --- Error messages -----------------------------------------------------------


@pytest.mark.parametrize(
    "error, message",
    [
        (APIKeyError("No key"), "No key"),
        (APIInactiveError("dead"), "The API is currently down. Try again later."),
        (APIInvalidKey("Invalid key"), "Your API key is invalid! Remove your key and add a new one"),
        (APINotFound("Not found"), "API has responded with the following error: `Not found`"),
        (APIConnectionError("500 oops"), "API has responded with the following error: `500 oops`"),
        (APIError("{braces}"), "API has responded with the following error: `{braces}`"),
        (ValueError("not ours"), ""),
    ],
)
def test_error_messages(error, message):
    assert error_message(error) == message


async def test_bot_maps_api_errors_from_any_cog():
    from discord import app_commands

    from gw2bot.bot import GW2Bot
    from gw2bot.config import Settings

    bot = GW2Bot(Settings(token="tok"))
    try:
        interaction = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        # A cog without its own error handler
        interaction.command.binding = object()
        error = app_commands.CommandInvokeError(interaction.command, APIInvalidKey("Invalid key"))
        await bot.on_app_command_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with(
            "Your API key is invalid! Remove your key and add a new one", ephemeral=True
        )
    finally:
        await bot.data.close()


# --- Emojis -------------------------------------------------------------------


GOLD = MagicMock(spec=discord.Emoji)
GOLD.__str__.return_value = "<:gold:42>"


def emojis(ids=None):
    bot = MagicMock()
    bot.get_emoji = lambda emoji_id: GOLD if emoji_id == 42 else None
    service = Emojis(bot, MagicMock())
    service.ids = {"gold": 42} if ids is None else ids
    return service


def interaction(in_guild=True, can_use=True):
    ctx = MagicMock(spec=discord.Interaction)
    if in_guild:
        ctx.guild = MagicMock()
        ctx.channel.permissions_for.return_value.external_emojis = can_use
    else:
        ctx.guild = None
    return ctx


def test_emoji_in_guild_with_permission():
    assert emojis().get(interaction(), "gold") == "<:gold:42>"


def test_emoji_name_is_normalized():
    service = emojis({"daily_fractal": 42})
    assert service.get(interaction(), "Daily Fractal") == "<:gold:42>"


def test_emoji_without_external_emoji_permission():
    service = emojis()
    assert service.get(interaction(can_use=False), "gold") == ""
    assert service.get(interaction(can_use=False), "gold", fallback=True, fallback_fmt=" {} ") == " gold "


def test_emoji_in_dm():
    assert emojis().get(interaction(in_guild=False), "gold") == "<:gold:42>"
    assert emojis().get(interaction(in_guild=False), "silver") == ""


def test_unknown_emoji_falls_back():
    service = emojis()
    assert service.get(interaction(), "silver") == ""
    assert service.get(interaction(), "silver", fallback=True) == "silver"


def test_emoji_object_and_forced():
    service = emojis()
    assert service.get(interaction(), "gold", return_obj=True) is GOLD
    # force_emoji skips the permission check
    assert service.get(interaction(can_use=False), "gold", force_emoji=True) == "<:gold:42>"
    assert service.get(None, "silver", force_emoji=True) is None


def test_emoji_for_webhook_uses_everyone_permissions():
    hook = MagicMock(spec=discord.Webhook)
    hook.guild = MagicMock()
    hook.channel.permissions_for.return_value.external_emojis = True
    assert emojis().get(hook, "gold") == "<:gold:42>"
    hook.channel.permissions_for.assert_called_with(hook.guild.default_role)


def test_emoji_without_context():
    assert emojis().get(None, "gold") == ""
    assert emojis().get(None, "gold", fallback=True) == "gold"


async def test_emoji_register_updates_map_and_config():
    service = emojis({})
    service.config.update = AsyncMock()
    await service.register("Gold", 42)
    assert service.ids == {"gold": 42}
    service.config.update.assert_awaited_once_with({"emojis.gold": 42})


def test_emoji_for_webhook_without_permission_or_in_dm():
    hook = MagicMock(spec=discord.Webhook)
    hook.guild = MagicMock()
    hook.channel.permissions_for.return_value.external_emojis = False
    assert emojis().get(hook, "gold") == ""
    assert emojis().get(hook, "gold", fallback=True) == "gold"
    hook.guild = None
    assert emojis().get(hook, "gold") == "<:gold:42>"
