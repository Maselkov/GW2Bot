"""Adapter between the tests and the code under test.

Tests only call the plain functions in this module, never the cog's mixins
directly. When a piece of logic moves during the rewrite, repoint the
matching function here; the tests themselves should not need to change.
"""
import asyncio
import datetime
import json
import logging
import pathlib
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import time_machine

from gw2bot.cogs.base import GW2Cog
from gw2bot.cogs.guildwars2.achievements import AchievementsMixin
from gw2bot.cogs.guildwars2.characters import CharactersMixin
from gw2bot.cogs.guildwars2.commerce import CommerceMixin
from gw2bot.cogs.guildwars2 import daily
from gw2bot.cogs.guildwars2.daily import DailyMixin
from gw2bot.cogs.guildwars2.database import DatabaseMixin
from gw2bot.cogs.guildwars2.events import EventsMixin
from gw2bot.cogs.guildwars2.misc import MiscMixin
from gw2bot.cogs.guildwars2.skills import SkillsMixin
from gw2bot.cogs.guildwars2.utils import chat, db
from gw2bot.cogs.guildwars2.wvw import WvwMixin, match_summary

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "gw2bot" / "data"
UTC = datetime.timezone.utc


def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


_GAMEDATA = _load("gamedata.json")
_INSTABILITIES = _load("instabilities.json")


class _StubEmojis:
    """No registered emojis: get() gives the fallback text, like an emoji
    the bot can't use."""

    ids = {}

    def get(self, ctx, emoji, *, fallback=False, fallback_fmt="{}", **kwargs):
        return fallback_fmt.format(emoji) if fallback else ""


def _fake_bot(session=None, users=None):
    """A bot with the services cogs use: game data, the API client (over
    `session`), users' keys (over the `users` repository) and emojis."""
    from gw2bot.keys import ApiKeys

    bot = MagicMock()
    bot.gamedata = _GAMEDATA
    bot.instabilities = _INSTABILITIES
    bot.gw2api = _client(session) if session is not None else None
    if users is not None:
        bot.data.users = users
        bot.keys = ApiKeys(users)
    bot.gw2_emojis = _StubEmojis()
    return bot


class _Harness(
    GW2Cog,
    AchievementsMixin,
    CharactersMixin,
    CommerceMixin,
    DailyMixin,
    DatabaseMixin,
    EventsMixin,
    MiscMixin,
    SkillsMixin,
    WvwMixin,
):
    """Just enough of the cog's state for its non-Discord logic to run."""

    def __init__(self, session=None, users=None):
        super().__init__(_fake_bot(session, users))
        self.log = logging.getLogger("tests")
        self.session = session


def _at(when):
    """Freeze the clock at `when` (a date means noon UTC that day)."""
    if not isinstance(when, datetime.datetime):
        when = datetime.datetime.combine(when, datetime.time(12), tzinfo=UTC)
    return time_machine.travel(when, tick=False)


# --- Items and coins -------------------------------------------------------

def chat_code(item_id, count=1, skin_id=None, upgrades=()):
    return _Harness().generate_chat_code(item_id, count, skin_id, list(upgrades))


def format_coins(copper):
    return _Harness().gold_to_coins(None, copper)


# --- Formatting ------------------------------------------------------------

def format_age(seconds, short=False):
    return CharactersMixin.format_age(seconds, short=short)


def profession_icon(name):
    return CharactersMixin.get_profession_icon(None, name)


def readable_attribute(name):
    return _Harness().readable_attribute(name)


def format_timedelta(td):
    return _Harness().format_timedelta(td)


def embed_list_lines(lines, field_name="Field", **kwargs):
    """Return the embed's fields as a list of (name, value)."""
    import discord

    embed = chat.embed_list_lines(discord.Embed(), lines, field_name, **kwargs)
    return [(f.name, f.value) for f in embed.fields]


def cleanup_xml_tags(text):
    return chat.cleanup_xml_tags(text)


def search_pattern(text):
    return db.prepare_search(text)


# --- Achievements ----------------------------------------------------------

def tier_progress(tiers, progress):
    return _Harness().tier_progress(tiers, progress)


def max_ap(achievement, repeatable=False):
    return _Harness().max_ap(achievement, repeatable)


def earned_ap(achievement, progress):
    return _Harness().earned_ap(achievement, progress)


# --- Skills ----------------------------------------------------------------

def skill_fields(skill):
    """List of (field, value) shown for a skill's facts."""
    return [(f["field"], f.get("value")) for f in _Harness().get_skill_fields(skill)]


# --- Dailies (all evaluated as of noon UTC on `date`) ----------------------

def year_day(date):
    with _at(date):
        return _Harness().get_year_day(tomorrow=False)


def daily_rotation(categories, names):
    return daily.daily_rotation(categories, names)


def daily_categories(saved):
    return daily.normalize_categories(saved)


def daily_fields(categories, cache, now, tomorrow=False):
    """[(name, value)] of the daily embed, given the cached rotation."""
    harness = _Harness()
    harness.bot.user.name = "GW2Bot"
    doc = {"cache": {"dailies": cache, "dailies_tomorrow": cache}}
    with _at(now):
        embed = asyncio.run(harness.daily_embed(categories, doc=doc, tomorrow=tomorrow))
    return [(f.name, f.value) for f in embed.fields]


def pact_supply_agents(date):
    with _at(date):
        return _Harness().get_psna()


def instabilities(fractal_level, date):
    with _at(date):
        names = _Harness().get_instabilities(fractal_level, tomorrow=False)
    return names.split("\n") if names is not None else None


def cm_instabilities(date):
    """{CM fractal name: [instability names]}."""
    with _at(date):
        text = _Harness().get_cm_instabilities(tomorrow=False)
    result = {}
    current = None
    for line in text.split("\n"):
        if line in _GAMEDATA["fractals"]:
            current = line
            result[current] = []
        else:
            result[current].append(line)
    return result


# --- WvW --------------------------------------------------------------------

def wvw_match_summary(match, team_id):
    return match_summary(match, team_id)


def find_wvw_team(team):
    return _Harness().find_team(team)


def wvw_team_choices(current):
    """[(name, value)] offered by the team autocomplete."""
    choices = asyncio.run(_Harness().team_autocomplete(None, current))
    return [(c.name, c.value) for c in choices]


# --- Event timers ----------------------------------------------------------

def upcoming_bosses(now, limit=8):
    """[(boss name, datetime)] for the next `limit` world bosses."""
    with _at(now):
        harness = _Harness()
        harness.boss_schedule = harness.generate_schedule()
        bosses = harness.get_upcoming_bosses(limit)
    return [
        (b["name"], datetime.datetime.fromtimestamp(int(b["time"][3:-3]), UTC))
        for b in bosses
    ]


def seconds_until_boss(name, now):
    with _at(now):
        harness = _Harness()
        harness.boss_schedule = harness.generate_schedule()
        return harness.get_time_until_event({"type": "boss", "name": name})


def seconds_until_phase(group, map_name, phase, now):
    reminder = {"type": "event", "group": group, "map_name": map_name, "name": phase}
    with _at(now):
        return _Harness().get_time_until_event(reminder)


def timer_titles():
    """{group: title} for every event-timer group in the game data."""
    groups = [g for g in _GAMEDATA["event_timers"] if g != "bosses"]
    titles = {}
    for group in groups:
        embed = asyncio.run(_Harness().timer_embed(None, group))
        titles[group] = embed.title
    return titles


def timer_state(group, now):
    """{map name: (current phase or None, next phase, datetime of next phase)}."""
    with _at(now):
        embed = asyncio.run(_Harness().timer_embed(None, group))
    state = {}
    for field in embed.fields:
        current = re.search(r"Current phase: \*\*(.+?)\*\*", field.value)
        nxt = re.search(r"Next phase: \*\*(.+?)\*\* <t:(\d+):R>", field.value)
        state[field.name] = (
            current.group(1) if current else None,
            nxt.group(1),
            datetime.datetime.fromtimestamp(int(nxt.group(2)), UTC),
        )
    return state


# --- GW2 API ---------------------------------------------------------------

def _client(session):
    """A Client whose retry waits are recorded in session.delays, not slept."""
    from gw2bot.gw2api import Client

    async def sleep(delay):
        session.delays.append(delay)

    return Client(session, sleep=sleep)


class FakeResponse:
    def __init__(self, session, status, body, headers):
        self.session = session
        self.status = status
        self._body = body
        self.headers = headers

    async def json(self):
        import aiohttp

        if isinstance(self._body, str):
            raise aiohttp.ContentTypeError(MagicMock(), ())
        return self._body

    async def __aenter__(self):
        self.session.in_flight += 1
        self.session.max_in_flight = max(self.session.max_in_flight, self.session.in_flight)
        # Let other requests start, so concurrency limits are observable
        for _ in range(3):
            await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc):
        self.session.in_flight -= 1
        return False


class FakeFailure:
    """Raised when the request is made: a timeout or network error."""

    def __init__(self, error):
        self.error = error

    async def __aenter__(self):
        raise self.error

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Serves queued responses to the GW2 API client.

    Each response is (status, body), (status, body, headers) or an
    exception to raise; a str body is a non-JSON page. The last response
    repeats once the queue is exhausted. Records requests as (url, query
    params, headers) and retry waits in `delays`.
    """

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.delays = []
        self.in_flight = 0
        self.max_in_flight = 0

    def get(self, url, headers=None, params=None, timeout=None):
        self.requests.append((url, dict(params or []), dict(headers or {})))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, BaseException):
            return FakeFailure(response)
        status, body, *rest = response
        return FakeResponse(self, status, body, rest[0] if rest else {})


async def api_get(session, endpoint, key=None, schema=None):
    """GET through the bot's GW2 API client, using `session` for HTTP."""
    return await _client(session).get(endpoint, key=key, schema=schema)


async def api_get_many(session, endpoints, key=None):
    return await _client(session).get_many(endpoints, key=key)


class FakeUserRepo:
    """bot.data.users, as used by fetch_key and the rename check."""

    def __init__(self, doc):
        self.doc = doc
        self.writes = []

    async def get(self, user_id):
        return self.doc

    async def update(self, user_id, fields, op="set"):
        self.writes.append((op, fields))


async def fetch_account(session, stored, user_id=1):
    """Call /account as a user whose stored settings are `stored`.

    Returns (account data, database writes, DMs sent to the user), after
    any background work the call started has finished.
    """
    from unittest.mock import AsyncMock

    users = FakeUserRepo(stored)
    harness = _Harness(session, users)
    user = MagicMock(id=user_id)
    user.send = AsyncMock()
    data = await harness.call_api("account", user)
    await asyncio.gather(*harness.keys.background_tasks, return_exceptions=True)
    sent = [call.args[0] for call in user.send.await_args_list]
    return data, users.writes, sent


def api_error_message(error):
    """The message shown to the user for an exception from the API layer."""
    from gw2bot.errors import error_message

    return error_message(error)


# --- Update notes ----------------------------------------------------------

def patch_notes_markdown(html):
    """Discord markdown for a forum post's HTML."""
    from gw2bot.cogs.guildwars2.utils.markdown import html_to_markdown

    return html_to_markdown(html)


# --- Build images ----------------------------------------------------------

class FakeImageSession:
    """Serves {url: image bytes}; any other URL is a 404. Records requests."""

    def __init__(self, images):
        self.images = images
        self.requests = []

    def get(self, url, timeout=None):
        self.requests.append(url)
        return _FakeImageResponse(self.images.get(url))


class _FakeImageResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        if self.body is None:
            import aiohttp

            raise aiohttp.ClientResponseError(MagicMock(), (), status=404)

    async def read(self):
        return self.body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def render_build(session, specializations, skills):
    """PNG bytes of a build image, or None when there's nothing to draw.

    specializations: [{"spec_doc", "active_traits", "trait_docs"}] as stored
    by the bot; skills: skill docs with an "icon" URL.
    """
    from types import SimpleNamespace

    from PIL import ImageFont

    from gw2bot.cogs.guildwars2.skills import Build

    cog = SimpleNamespace(
        session=session,
        bot=SimpleNamespace(loop=asyncio.get_running_loop()),
        font=ImageFont.load_default(),
    )
    file = await Build(cog, None, specializations, skills, "[&code]").render()
    return file.fp.read() if file else None


# --- Database-backed logic -------------------------------------------------

async def total_possible_ap(db):
    """Maximum achievement points, from the cached achievements in `db`."""
    harness = _Harness()
    harness.db = db
    return await harness.total_possible_ap()


async def account_ap(db, progress, account):
    """A user's AP from /account/achievements progress and /account."""
    harness = _Harness()
    harness.db = db
    return await harness.calculate_user_ap(progress, account)


# --- Update notes from the forum -------------------------------------------

class FakeCollection:
    """The find_one/insert_one/update_one subset used on gw2.updates."""

    def __init__(self):
        self.docs = []

    async def find_one(self, query):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in query.items())), None)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, query, update):
        doc = await self.find_one(query)
        doc.update(update["$set"])


class FakePageSession:
    """Serves {url: (status, text)}; anything else is a 404."""

    def __init__(self, pages):
        self.pages = pages

    def get(self, url, timeout=None):
        status, text = self.pages.get(url, (404, "Not found"))
        response = MagicMock(status=status)

        async def read_text():
            return text

        response.text = read_text
        return _AsyncContext(response)


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


class UpdateNotesChecker:
    """Runs the update-notes check against a fake forum, keeping state
    (sent counts, blocked flag) between checks like the running bot does."""

    def __init__(self, pages):
        # (sic) the class name has a doubled "i"
        from gw2bot.cogs.guildwars2.notifiers import NotiifiersMixin

        class Notifier(NotiifiersMixin):
            pass

        self.notifier = Notifier()
        self.notifier.log = logging.getLogger("tests.update_notes")
        self.notifier.bot = MagicMock()
        self.updates = FakeCollection()
        self.notifier.bot.data.gw2.updates = self.updates
        self.pages = pages
        self.notifier.session = FakePageSession(pages)

    async def check(self):
        """[(title, markdown, minor)] for the notes the bot would send."""
        notes = await self.notifier.update_notification("12345") or []
        return [
            (embed.title, embed.fields[0].value, minor) for embed, text, minor in notes
        ]


# --- Settings commands ------------------------------------------------------

class MemorySettingsRepo:
    """In-memory stand-in for a SettingsRepo (set, and equality queries)."""

    def __init__(self):
        self.docs = {}

    async def get(self, entity_id):
        doc = self.docs.get(entity_id)
        return {**doc, "_id": entity_id} if doc else {}

    async def update(self, entity_id, fields, op="set"):
        assert op in ("set", "$set"), op
        doc = self.docs.setdefault(entity_id, {})
        for name, value in fields.items():
            *parents, last = name.split(".")
            target = doc
            for part in parents:
                target = target.setdefault(part, {})
            target[last] = value

    async def find(self, query=None, *, batch_size=100):
        def value(doc, name):
            for part in name.split("."):
                doc = doc.get(part) if isinstance(doc, dict) else None
            return doc

        for entity_id, doc in list(self.docs.items()):
            if all(value(doc, k) == v for k, v in (query or {}).items()):
                yield {**doc, "_id": entity_id}


class SettingsCommands:
    """Runs server/channel settings commands against in-memory settings,
    which survive a simulated restart."""

    def __init__(self):
        self.guilds = MemorySettingsRepo()
        self.channels = MemorySettingsRepo()
        self.start()

    def start(self):
        """(Re)create the cog, as after a restart: in-memory caches are lost."""
        from unittest.mock import AsyncMock

        from gw2bot.cogs.guildwars2.evtc import EvtcMixin
        from gw2bot.cogs.guildwars2.guildmanage import GuildManageMixin
        from gw2bot.cogs.guildwars2.skills import SkillsMixin

        class Cog(GuildManageMixin, SkillsMixin, EvtcMixin):
            pass

        self.cog = Cog()
        self.cog.bot = MagicMock()
        self.cog.bot.data.guilds = self.guilds
        self.cog.bot.data.channels = self.channels
        self.cog.chatcode_preview_opted_out_guilds = set()
        self.cog.force_guild_account_names = AsyncMock()

    async def load(self):
        await self.cog.prepare_linkpreview_guild_cache()

    async def run(self, command, guild_id=10, **options):
        """The reply to running `command` (a method name) in a guild."""
        from unittest.mock import AsyncMock

        interaction = MagicMock()
        interaction.guild.id = guild_id
        interaction.response.send_message = AsyncMock()
        await getattr(type(self.cog), command).callback(self.cog, interaction, **options)
        call = interaction.response.send_message.await_args
        return call.args[0] if call.args else call.kwargs.get("content")

    def channel(self, channel_id):
        channel = MagicMock(id=channel_id, mention=f"<#{channel_id}>")
        channel.permissions_for.return_value.embed_links = True
        return channel


class EvtcUploads:
    """Feeds messages to the EVTC upload listener, with channel settings in
    memory; records what was processed and deleted."""

    def __init__(self):
        from unittest.mock import AsyncMock

        from gw2bot.cogs.guildwars2.evtc import EvtcMixin

        class Cog(EvtcMixin):
            pass

        self.channels = MemorySettingsRepo()
        self.cog = Cog()
        self.cog.bot = MagicMock()
        self.cog.bot.data.channels = self.channels
        self.cog.process_evtc = AsyncMock()

    async def post(self, filename, *, channel_id=500, in_guild=True, can_manage=True):
        """Returns (processed, deleted) for a message with one attachment."""
        from unittest.mock import AsyncMock

        message = MagicMock()
        message.attachments = [MagicMock(filename=filename)]
        message.channel.id = channel_id
        if in_guild:
            message.guild.me = MagicMock(name="me")
            message.channel.permissions_for.return_value.manage_messages = can_manage
        else:
            message.guild = None
        message.delete = AsyncMock()
        self.cog.process_evtc.reset_mock()
        await type(self.cog).on_message(self.cog, message)
        return self.cog.process_evtc.await_count == 1, message.delete.await_count == 1


class MemoryCollection:
    """In-memory stand-in for a Mongo collection (equality filters only).
    Like Mongo, inserted documents get a generated _id."""

    def __init__(self):
        self.docs = []
        self._next_id = 0

    def _matches(self, doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    async def find_one(self, query):
        return next((dict(d) for d in self.docs if self._matches(d, query)), None)

    async def insert_one(self, doc):
        self._next_id += 1
        doc.setdefault("_id", f"oid{self._next_id}")
        self.docs.append(dict(doc))

    async def delete_one(self, query):
        for i, doc in enumerate(self.docs):
            if self._matches(doc, query):
                del self.docs[i]
                return

    async def delete_many(self, query):
        self.docs = [d for d in self.docs if not self._matches(d, query)]


class EvtcApiKeys:
    """Runs /evtc api_key against an in-memory key collection."""

    def __init__(self):
        from gw2bot.cogs.guildwars2.evtc import EvtcMixin

        class Cog(EvtcMixin):
            pass

        self.keys = MemoryCollection()
        self.cog = Cog()
        self.cog.db = MagicMock()
        self.cog.db.evtc.api_keys = self.keys

    async def run(self, operation, user_id=1):
        """The reply to `/evtc api_key <operation>`."""
        from unittest.mock import AsyncMock

        interaction = MagicMock()
        interaction.user.id = user_id
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        await type(self.cog).evtc_api_key.callback(self.cog, interaction, operation)
        return interaction.followup.send.await_args.args[0]

    def accepted_tokens(self, user_id=1):
        """The tokens the upload API would accept for this user."""
        return {d["token"] for d in self.keys.docs if d["user"] == user_id}


# --- Command handlers -------------------------------------------------------

def stored_key(permissions, account_name="Example.1234"):
    """A user's stored settings with one key (synthetic, never real data)."""
    key = {"key": "KEY", "account_name": account_name, "permissions": list(permissions), "name": ""}
    return {"key": key, "keys": [key]}


async def run_command(cog_for, command, responses, *, permissions, users=None, **options):
    """Run a slash command's handler with a fake interaction.

    cog_for(session, users) builds the cog; `responses` are the API
    responses in request order (see FakeSession); `users` is the users
    repository (default: one user with a key with `permissions`). Returns
    (what was sent, API requests). What was sent is the reply's embed as a
    dict, or its content if there's no embed: the followup's if the command
    deferred, else the direct response's.
    """
    from unittest.mock import AsyncMock

    session = FakeSession(*responses)
    users = users or FakeUserRepo(stored_key(permissions))
    cog = cog_for(session, users)
    interaction = MagicMock()
    interaction.user.id = 1
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    await command.callback(cog, interaction, **options)
    reply = interaction.followup.send if interaction.followup.send.await_count else interaction.response.send_message
    if interaction.followup.send.await_count:
        # A followup needs a deferred (or answered) interaction first
        assert interaction.response.defer.await_count or interaction.response.send_message.await_count
    call = reply.await_args
    embed = call.kwargs.get("embed")
    sent = embed.to_dict() if embed else call.args[0] if call.args else call.kwargs.get("content")
    return sent, [(url, params) for url, params, _ in session.requests]


async def pvp(command, stats, *, rank_icon="https://render/rank.png", permissions=("account", "pvp"), **options):
    """Run /pvp stats or /pvp professions against synthetic pvp/stats."""
    responses = [(200, stats)]
    if command == "stats":
        responses.append((200, {"id": 1, "icon": rank_icon}))
    from gw2bot.cogs.pvp import Pvp

    handler = {"stats": Pvp.pvp_stats, "professions": Pvp.pvp_professions}[command]

    def cog_for(session, users):
        return Pvp(_fake_bot(session, users))

    return await run_command(cog_for, handler, responses, permissions=permissions, **options)


def pvp_win_ratio(record):
    from gw2bot.cogs.pvp import win_ratio

    return win_ratio(record)


def pvp_extremes(stats, professions):
    """Most/least played and highest/lowest win rate among `professions`."""
    from gw2bot.cogs.pvp import extremes, profession_records

    return extremes(profession_records(stats, professions))


async def wizards_vault(daily, weekly, special, *, wallet=None, now, permissions=("account", "progression")):
    """Run /wizardsvault at `now`; `wallet` is served if the key has the
    wallet permission."""
    responses = [(200, daily), (200, weekly), (200, special)]
    if "wallet" in permissions:
        responses.append((200, wallet or []))
    from gw2bot.cogs.wizardsvault import WizardsVault

    def cog_for(session, users):
        return WizardsVault(_fake_bot(session, users))

    with _at(now):
        return await run_command(cog_for, WizardsVault.wizards_vault, responses, permissions=permissions)


class MemoryCollection:
    """In-memory stand-in for a collection: find_one by _id, and find with
    a regex on name plus an optional $nin on flags (the item searches)."""

    def __init__(self, docs=()):
        self.docs = {doc["_id"]: doc for doc in docs}

    async def find_one(self, query):
        return self.docs.get(query["_id"])

    def find(self, query):
        def matches(doc):
            if "name" in query and not query["name"].search(doc["name"]):
                return False
            excluded = query.get("flags", {}).get("$nin", [])
            return not set(doc.get("flags", [])) & set(excluded)

        found = [doc for doc in self.docs.values() if matches(doc)]

        class Cursor:
            async def to_list(self, length):
                return found[:length] if length else found

        return Cursor()


async def commerce(command, responses, *, items=(), permissions=("account", "tradingpost"), users=None, **options):
    """Run a /tp or /gem command; `items` are the cached item documents."""
    from gw2bot.cogs.guildwars2.commerce import CommerceMixin

    handler = getattr(CommerceMixin, command)

    def cog_for(session, users):
        cog = _Harness(session, users)
        cog.db = SimpleNamespace(items=MemoryCollection(items))
        return cog

    return await run_command(cog_for, handler, responses, permissions=permissions, users=users, **options)


async def tp_item_search(text, items):
    """The /tp price autocomplete choices for `text`, as (name, value)."""
    from gw2bot.cogs.guildwars2.commerce import CommerceMixin

    cog = _Harness()
    cog.db = SimpleNamespace(items=MemoryCollection(items))
    choices = await CommerceMixin.tp_autocomplete(cog, MagicMock(), text)
    return [(c.name, c.value) for c in choices]
