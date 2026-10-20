"""The bot, the clock, and running slash commands."""
import datetime
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock

import time_machine

from .db import FakeUserRepo
from .http import FakeSession

DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / "gw2bot" / "data"
UTC = datetime.timezone.utc


def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


GAMEDATA = _load("gamedata.json")
INSTABILITIES = _load("instabilities.json")


class StubEmojis:
    """No registered emojis: get() gives the fallback text, like an emoji
    the bot can't use."""

    ids = {}

    def get(self, ctx, emoji, *, fallback=False, fallback_fmt="{}", **kwargs):
        return fallback_fmt.format(emoji) if fallback else ""


def client(session):
    """A Client whose retry waits are recorded in session.delays, not slept."""
    from gw2bot.gw2api import Client

    async def sleep(delay):
        session.delays.append(delay)

    return Client(session, sleep=sleep)


def fake_bot(session=None, users=None):
    """A bot with the services cogs use: game data, the API client (over
    `session`), users' keys (over the `users` settings) and emojis."""
    from gw2bot.keys import ApiKeys

    bot = MagicMock()
    bot.user.name = "GW2Bot"
    bot.gamedata = GAMEDATA
    bot.instabilities = INSTABILITIES
    bot.session = session
    bot.gw2api = client(session) if session is not None else None
    if users is not None:
        bot.data.users = users
        bot.keys = ApiKeys(users)
    bot.gw2_emojis = StubEmojis()
    return bot


def at(when):
    """Freeze the clock at `when` (a date means noon UTC that day). An
    aware time also sets the process's timezone to its zone."""
    if not isinstance(when, datetime.datetime):
        when = datetime.datetime.combine(when, datetime.time(12), tzinfo=UTC)
    return time_machine.travel(when, tick=False)


def stored_key(permissions, account_name="Example.1234"):
    """A user's stored settings with one key (synthetic, never real data)."""
    key = {"key": "KEY", "account_name": account_name, "permissions": list(permissions), "name": ""}
    return {"key": key, "keys": [key]}


async def run_command(cog_for, command, responses, *, permissions, users=None, pages=(), head_error=None,
                      on_interaction=None, **options):
    """Run a slash command's handler with a fake interaction.

    cog_for(session, users) builds the cog; `responses` are the API
    responses in request order (see FakeSession); `users` is the users
    repository (default: one user with a key with `permissions`). Returns
    (what was sent, API requests). What was sent is the reply's embed as a
    dict, or its content if there's no embed: the followup's if the command
    deferred, else the direct response's. `pages` are the wiki pages that
    exist, and `head_error` makes checking them fail (see FakeSession).
    on_interaction(interaction) is called before running the command.
    """
    session = FakeSession(*responses, pages=pages, head_error=head_error)
    users = users or FakeUserRepo(stored_key(permissions))
    cog = cog_for(session, users)
    interaction = MagicMock()
    interaction.user.id = 1
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.user.send = AsyncMock()
    if on_interaction:
        on_interaction(interaction)
    await command.callback(cog, interaction, **options)
    reply = interaction.followup.send if interaction.followup.send.await_count else interaction.response.send_message
    if interaction.followup.send.await_count:
        # A followup needs a deferred (or answered) interaction first
        assert interaction.response.defer.await_count or interaction.response.send_message.await_count
    call = reply.await_args
    embed = call.kwargs.get("embed")
    sent = embed.to_dict() if embed else call.args[0] if call.args else call.kwargs.get("content")
    return sent, [(url, params) for url, params, _ in session.requests]
