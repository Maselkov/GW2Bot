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
from gw2bot.cogs import daily
from gw2bot.cogs.guildwars2.database import DatabaseMixin
from gw2bot.cogs.guildwars2.events import EventsMixin
from gw2bot.utils import chat, db

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
    bot.user.name = "GW2Bot"
    bot.gamedata = _GAMEDATA
    bot.instabilities = _INSTABILITIES
    bot.session = session
    bot.gw2api = _client(session) if session is not None else None
    if users is not None:
        bot.data.users = users
        bot.keys = ApiKeys(users)
    bot.gw2_emojis = _StubEmojis()
    return bot


class _Harness(
    GW2Cog,
    DatabaseMixin,
    EventsMixin,
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
    from gw2bot.cogs.misc import generate_chat_code

    return generate_chat_code(item_id, count, skin_id, list(upgrades))


def format_coins(copper):
    return _Harness().gold_to_coins(None, copper)


# --- Formatting ------------------------------------------------------------

def format_age(seconds, short=False):
    from gw2bot.utils.chat import format_age

    return format_age(seconds, short=short)


def profession_icon(name):
    from gw2bot.utils.wiki import profession_icon_url

    return profession_icon_url(name)


def readable_attribute(name):
    from gw2bot.cogs.characters import readable_attribute

    return readable_attribute(name)


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
    from gw2bot.cogs.achievements import tier_progress

    return tier_progress(tiers, progress)


def max_ap(achievement, repeatable=False):
    from gw2bot.cogs.achievements import max_ap

    return max_ap(achievement, repeatable)


def earned_ap(achievement, progress):
    from gw2bot.cogs.achievements import earned_ap

    return earned_ap(achievement, progress)


# --- Skills ----------------------------------------------------------------

def skill_fields(skill):
    """List of (field, value) shown for a skill's facts."""
    from gw2bot.cogs.skills import skill_fields

    return [(f["field"], f.get("value")) for f in skill_fields(skill)]


async def skill_command(command, *, skills=(), traits=(), pages=(), wiki_error=None, **options):
    """Run /skill or /trait with the cached `skills` and `traits`; `pages`
    are the wiki pages that exist, and wiki_error ("timeout" or
    "connection") makes the wiki unreachable. Returns (what was sent, wiki
    URLs checked)."""
    import aiohttp

    head_error = {None: None, "timeout": asyncio.TimeoutError(), "connection": aiohttp.ClientConnectionError()}[
        wiki_error
    ]
    from gw2bot.cogs.skills import Skills

    handler = {"skill": Skills.skillinfo, "trait": Skills.traitinfo}[command]
    sessions = []

    def cog_for(session, users):
        sessions.append(session)
        cog = Skills(_fake_bot(session, users))
        cog.db = gw2_db(skills=skills, traits=traits)
        return cog

    sent, _ = await run_command(cog_for, handler, [], permissions=(), pages=pages, head_error=head_error, **options)
    return sent, sessions[0].heads


async def skill_search(command, text, *, skills=(), traits=()):
    """The /skill or /trait autocomplete choices for `text`, as (name, value)."""
    from gw2bot.cogs.skills import Skills

    cog = Skills(_fake_bot())
    cog.db = gw2_db(skills=skills, traits=traits)
    autocomplete = {"skill": cog.skill_autocomplete, "trait": cog.trait_autocomplete}[command]
    return [(c.name, c.value) for c in await autocomplete(MagicMock(), text)]


# --- Dailies (all evaluated as of noon UTC on `date`) ----------------------

def _daily():
    return daily.Daily(_fake_bot())


def year_day(date):
    with _at(date):
        return _daily().get_year_day(tomorrow=False)


def daily_rotation(categories, names):
    return daily.daily_rotation(categories, names)


def daily_categories(saved):
    return daily.normalize_categories(saved)


def daily_fields(categories, cache, now, tomorrow=False):
    """[(name, value)] of the daily embed, given the cached rotation."""
    harness = _daily()
    doc = {"cache": {"dailies": cache, "dailies_tomorrow": cache}}
    with _at(now):
        embed = asyncio.run(harness.daily_embed(categories, doc=doc, tomorrow=tomorrow))
    return [(f.name, f.value) for f in embed.fields]


def pact_supply_agents(date):
    with _at(date):
        return _daily().get_psna()


def instabilities(fractal_level, date):
    with _at(date):
        names = _daily().get_instabilities(fractal_level, tomorrow=False)
    return names.split("\n") if names is not None else None


def cm_instabilities(date):
    """{CM fractal name: [instability names]}."""
    with _at(date):
        text = _daily().get_cm_instabilities(tomorrow=False)
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
    from gw2bot.cogs.wvw import match_summary

    return match_summary(match, team_id)


def find_wvw_team(team):
    from gw2bot.cogs.wvw import find_team

    return find_team(_GAMEDATA, team)


def wvw_team_choices(current):
    """[(name, value)] offered by the team autocomplete."""
    from gw2bot.cogs.wvw import Wvw

    choices = asyncio.run(Wvw(_fake_bot()).team_autocomplete(None, current))
    return [(c.name, c.value) for c in choices]


async def wvw_info(responses, *, permissions=("account",), **options):
    """Run /wvw info; `responses`: account (without a team option), then
    wvw/matches."""
    from gw2bot.cogs.wvw import Wvw

    def cog_for(session, users):
        return Wvw(_fake_bot(session, users))

    return await run_command(cog_for, Wvw.wvw_info, responses, permissions=permissions, **options)


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

    HEAD requests (the bot checking a wiki page exists) are 200 for the
    URLs in `pages`, else 404, and recorded in `heads`; `head_error` (an
    exception) makes them all fail.
    """

    def __init__(self, *responses, pages=(), head_error=None):
        self.responses = list(responses)
        self.pages = set(pages)
        self.head_error = head_error
        self.heads = []
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

    def head(self, url, **kwargs):
        self.heads.append(url)
        if self.head_error:
            return FakeFailure(self.head_error)
        return FakeResponse(self, 200 if url in self.pages else 404, None, {})


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
    from gw2bot.utils.markdown import html_to_markdown

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
    from gw2bot.builds import Build

    cog = SimpleNamespace(bot=SimpleNamespace(loop=asyncio.get_running_loop(), session=session))
    file = await Build(cog, None, specializations, skills, "[&code]").render()
    return file.fp.read() if file else None


# --- Database-backed logic -------------------------------------------------

async def total_possible_ap(db):
    """Maximum achievement points, from the cached achievements in `db`."""
    from gw2bot.cogs.achievements import total_possible_ap

    return await total_possible_ap(db.achievements)


async def account_ap(db, progress, account):
    """A user's AP from /account/achievements progress and /account."""
    from gw2bot.cogs.achievements import account_ap

    return await account_ap(db.achievements, progress, account)


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
        from gw2bot.cogs.guildwars2.chatlinks import ChatLinksMixin

        class Cog(GuildManageMixin, ChatLinksMixin, EvtcMixin):
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
    from unittest.mock import AsyncMock

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


class MemoryItems:
    """In-memory stand-in for a game data cache: find_one by _id, and find
    with a regex on name plus $nin / $ne conditions (searches)."""

    def __init__(self, docs=()):
        self.docs = {doc["_id"]: doc for doc in docs}

    async def find_one(self, query):
        try:
            return self.docs.get(query["_id"])
        except TypeError:
            # Like Mongo, a document as the id matches nothing here
            return None

    def find(self, query=None):
        query = query or {}

        def matches(doc):
            for field, condition in query.items():
                value = doc.get(field)
                if field == "name":
                    if not condition.search(value):
                        return False
                elif not isinstance(condition, dict):
                    if value != condition:
                        return False
                elif "$nin" in condition and set(value or []) & set(condition["$nin"]):
                    return False
                elif "$ne" in condition and value == condition["$ne"]:
                    return False
            return True

        found = [doc for doc in self.docs.values() if matches(doc)]

        class Cursor:
            def limit(self, length):
                del found[length:]
                return self

            async def to_list(self, length):
                return found[:length] if length else found

            def __aiter__(self):
                return self._iterate()

            async def _iterate(self):
                for doc in found:
                    yield doc

        return Cursor()


async def commerce(command, responses, *, items=(), permissions=("account", "tradingpost"), users=None, **options):
    """Run a /tp or /gem command; `items` are the cached item documents."""
    from gw2bot.cogs.commerce import Commerce

    handler = getattr(Commerce, command)

    def cog_for(session, users):
        cog = Commerce(_fake_bot(session, users))
        cog.db = SimpleNamespace(items=MemoryItems(items))
        return cog

    return await run_command(cog_for, handler, responses, permissions=permissions, users=users, **options)


async def tp_item_search(text, items):
    """The /tp price autocomplete choices for `text`, as (name, value)."""
    from gw2bot.cogs.commerce import Commerce

    cog = Commerce(_fake_bot())
    cog.db = SimpleNamespace(items=MemoryItems(items))
    choices = await Commerce.tp_autocomplete(cog, MagicMock(), text)
    return [(c.name, c.value) for c in choices]


def gw2_db(**collections):
    """A stand-in for the gw2 collections: {name: [documents]}."""
    return SimpleNamespace(**{name: MemoryItems(docs) for name, docs in collections.items()})


async def achievement(responses, achievement_name, *, db, permissions=("account", "progression")):
    """Run /achievement with the cached game data in `db` (see gw2_db)."""
    from gw2bot.cogs.achievements import Achievements

    def cog_for(session, users):
        cog = Achievements(_fake_bot(session, users))
        cog.db = db
        return cog

    return await run_command(
        cog_for, Achievements.achievementinfo, responses, permissions=permissions,
        achievement_name=achievement_name,
    )


async def achievement_search(text, db):
    """The /achievement autocomplete choices for `text`, as (name, value)."""
    from gw2bot.cogs.achievements import Achievements

    cog = Achievements(_fake_bot())
    cog.db = db
    choices = await Achievements.achievement_autocomplete(cog, MagicMock(), text)
    return [(c.name, c.value) for c in choices]


# Every currency and item id /wallet's overview shows
WALLET_CURRENCY_IDS = [1, 4, 2, 3, 18, 23, 16, 50, 47, 43, 40, 41, 37, 42, 38, 44, 49, 51, 32, 45, 25, 27,
                       19, 22, 20, 29, 34, 35, 15, 26, 31, 36, 65, 33, 69, 7, 24, 59, 28, 70, 58, 60,
                       61, 66, 64, 67, 68, 71, 62, 63, 72, 73, 75, 53, 55, 57, 54]
WALLET_ITEM_IDS = [79280, 79469, 79899, 80332, 81127, 81706, 86069, 86977, 87645, 88955, 89537, 90783,
                   92072, 92272, 46682, 70820, 71581]


async def wallet(responses, *, currencies, items, permissions=("account", "wallet", "inventories", "characters"),
                 random_value=0.5, **options):
    """Run /wallet. `responses`: account/wallet, then (for the overview)
    account/bank, account/inventory, account/materials and characters.
    random_value stands in for random.random() (the overview's
    occasional joke title)."""
    from unittest.mock import patch

    from gw2bot.cogs.wallet import Wallet

    def cog_for(session, users):
        cog = Wallet(_fake_bot(session, users))
        cog.db = gw2_db(currencies=currencies, items=items)
        return cog

    with patch("random.random", return_value=random_value):
        return await run_command(cog_for, Wallet.wallet, responses, permissions=permissions, **options)


async def items_in_account(responses, item_ids, *, permissions=("account", "inventories", "characters"), **options):
    """GW2Cog.find_items_in_account: `responses` are account/bank,
    account/inventory, account/materials, characters (and
    commerce/delivery with the tradingpost permission)."""
    session = FakeSession(*responses)
    cog = _Harness(session, FakeUserRepo(stored_key(permissions)))
    user = MagicMock(id=1)
    result = await cog.find_items_in_account(user, item_ids, **options)
    # Plain dicts, for comparing
    if options.get("flatten"):
        return dict(result)
    return {item: dict(places) for item, places in result.items()}


class MemoryEncounters:
    """In-memory stand-in for the EVTC encounters collection, for the
    /bosses report links: boss_id $in, a player, a date range and success;
    newest first."""

    def __init__(self, docs=()):
        self.docs = list(docs)

    def find(self, query):
        found = [
            doc for doc in self.docs
            if doc["boss_id"] in query["boss_id"]["$in"]
            and query["players"] in doc["players"]
            and query["date"]["$gte"] <= doc["date"] < query["date"]["$lt"]
            and doc["success"] == query["success"]
        ]

        class Cursor:
            def sort(self, field, direction):
                found.sort(key=lambda doc: doc[field], reverse=direction == -1)
                return self

            def limit(self, length):
                del found[length:]
                return self

            async def to_list(self, length):
                return found

        return Cursor()


def _account_cog(session=None, users=None, db=None, raids=None):
    from unittest.mock import AsyncMock

    from gw2bot.cogs.account import Account

    cog = Account(_fake_bot(session, users))
    cog.db = db or gw2_db()
    if not hasattr(cog.db, "encounters"):
        cog.db.encounters = MemoryEncounters()
    cog.bot.data.config.get = AsyncMock(return_value={"cache": {"raids": raids}})
    return cog


async def account_command(command, responses, *, permissions=("account",), db=None, raids=None, now=None,
                          **options):
    """Run /account, /li, /kp, /bosses, /search, /cats or /nodes. `db` is
    the game data cache (see gw2_db), `raids` the cached raid wings, and
    `now` freezes the clock."""
    import contextlib

    from gw2bot.cogs.account import Account

    handler = getattr(Account, command)

    def cog_for(session, users):
        return _account_cog(session, users, db=db, raids=raids)

    with _at(now) if now else contextlib.nullcontext():
        return await run_command(cog_for, handler, responses, permissions=permissions, **options)


async def account_item_search(text, items):
    """The /search autocomplete choices for `text`, as (name, value)."""
    cog = _account_cog(db=gw2_db(items=items))
    return [(c.name, c.value) for c in await cog.item_autocomplete(MagicMock(), text)]


# --- Characters ---------------------------------------------------------------

def _characters_cog(session=None, users=None, db=None, public=(), config=None, channel=None):
    """The characters commands' cog. `public` are the public characters'
    documents, `config` the bot's config document and `channel` the image
    channel (id 5)."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.characters import Characters

    cog = Characters(_fake_bot(session, users))
    cog.db = db or gw2_db()
    cog.db.characters = MemoryCollection()
    cog.db.characters.docs = [dict(doc) for doc in public]
    cog.bot.data.config.get = AsyncMock(return_value=config if config is not None else {})
    cog.bot.get_channel = lambda channel_id: channel if channel_id == 5 else None
    cog.bot.fetch_user = AsyncMock(side_effect=lambda user_id: MagicMock(id=user_id))
    return cog


def _character_handler(command):
    from gw2bot.cogs.characters import Characters

    if command.startswith("sab "):
        return getattr(Characters, "sab_" + command[4:])
    return getattr(Characters, "character_" + command)


async def character_command(command, responses, *, permissions=("account", "characters", "builds"), db=None,
                            public=(), config=None, channel=None, now=None, users=None, **options):
    """Run /character <command> or /sab <unlocks|zones> ("sab unlocks").

    Returns (what was sent, API requests, DMs to the user, public
    character documents afterwards)."""
    import contextlib

    cogs = []
    interactions = []

    def cog_for(session, users):
        cogs.append(_characters_cog(session, users, db=db, public=public, config=config, channel=channel))
        return cogs[0]

    with _at(now) if now else contextlib.nullcontext():
        sent, requests = await run_command(
            cog_for, _character_handler(command), responses, permissions=permissions, users=users,
            on_interaction=interactions.append, **options,
        )
    dms = [call.args[0] for call in interactions[0].user.send.await_args_list]
    return sent, requests, dms, cogs[0].db.characters.docs


async def character_attributes(level, profession, equipment, items=(), itemstats=()):
    """The /character gear attribute panel: {name: value} for a character
    wearing `equipment` (equipment tab entries), with `items` cached."""
    cog = _characters_cog(db=gw2_db(items=items, itemstats=itemstats))
    character = {"level": level, "profession": profession}
    return await cog.calculate_character_attributes(character, equipment)


async def character_choices(current, stored, responses=(), *, now):
    """The character autocomplete for `current`, for a user whose stored
    settings are `stored`. Returns (choices, database writes, API
    requests), after any background refresh finished."""
    session = FakeSession(*(responses or [(500, {})]))
    users = FakeUserRepo(stored)
    cog = _characters_cog(session, users)
    interaction = MagicMock()
    interaction.user.id = 1
    with _at(now):
        choices = await cog.character_autocomplete(interaction, current)
        for _ in range(10):
            await asyncio.sleep(0)
    return [c.name for c in choices], users.writes, [(url, params) for url, params, _ in session.requests]


# --- Guilds --------------------------------------------------------------------

class MemoryUsers:
    """Users' settings by Discord id (get/update), and find() by account
    name as /guild members uses it."""

    def __init__(self, docs):
        self.docs = docs
        self.writes = []

    async def get(self, user_id):
        return self.docs.get(user_id, {})

    async def update(self, user_id, fields, op="set"):
        self.writes.append((user_id, op, fields))

    async def find(self, query):
        """By account name ({"$or": [{"key.account_name": name}, ...]}), or
        top-level fields equal to a value or {"$ne": value}."""
        if "$or" in query:
            names = {next(iter(condition.values())) for condition in query["$or"]}
            for user_id, doc in self.docs.items():
                accounts = [doc.get("key", {}).get("account_name")]
                accounts += [k.get("account_name") for k in doc.get("keys", [])]
                if names & set(accounts):
                    yield {**doc, "_id": user_id}
            return
        for user_id, doc in list(self.docs.items()):
            def matches(field, condition):
                if isinstance(condition, dict):
                    return doc.get(field) != condition["$ne"]
                return doc.get(field) == condition

            if all(matches(f, c) for f, c in query.items()):
                yield {**doc, "_id": user_id}


async def guild_command(command, responses, *, permissions=("account", "guilds"), items=(), users=None,
                        discord_members=None, **options):
    """Run /guild <command>. `users` are other users' settings by Discord
    id (the caller is id 1); `discord_members` the Discord server's members
    by id, as {id: mention}, or None to run it in DMs."""
    from gw2bot.cogs.guild import Guild

    handler = getattr(Guild, "guild_" + command)
    repo = MemoryUsers({1: stored_key(permissions), **(users or {})})

    def cog_for(session, _):
        cog = Guild(_fake_bot(session, repo))
        cog.db = gw2_db(items=items)
        return cog

    def in_server(interaction):
        if discord_members is None:
            interaction.guild = None
            return
        interaction.guild.get_member = (
            lambda user_id: MagicMock(mention=discord_members[user_id]) if user_id in discord_members else None
        )

    return await run_command(cog_for, handler, responses, permissions=permissions, users=repo,
                             on_interaction=in_server, **options)


async def guild_choices(current, stored, responses=(), *, server_default=None, now):
    """The guild name autocomplete for `current`. Returns (choices as
    (name, value), database writes, API requests), after any background
    refresh finished."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.guild import guild_name_autocomplete

    session = FakeSession(*(responses or [(500, {})]))
    users = FakeUserRepo(stored)
    cog = _Harness(session, users)
    interaction = MagicMock()
    interaction.user.id = 1
    interaction.command.binding = cog
    cog.bot.data.guilds.get = AsyncMock(return_value={"guild_ingame": server_default} if server_default else {})
    with _at(now):
        choices = await guild_name_autocomplete(interaction, current)
        for _ in range(10):
            await asyncio.sleep(0)
    return ([(c.name, c.value) for c in choices], users.writes,
            [(url, params) for url, params, _ in session.requests])



# --- Misc -------------------------------------------------------------------------

class FakeWikiSession:
    """Serves wiki pages, {url: html}; `redirects` maps a search URL to the
    page it lands on (an exact match). Records (url, headers)."""

    def __init__(self, pages=None, redirects=None):
        self.pages = pages or {}
        self.redirects = redirects or {}
        self.requests = []

    def get(self, url, headers=None, **kwargs):
        self.requests.append((url, dict(headers or {})))
        target = self.redirects.get(url)
        response = MagicMock(history=[MagicMock()] if target else [], url=target or url)

        async def text():
            return self.pages[target or url]

        response.text = text
        return _AsyncContext(response)


def _misc_cog(session=None, users=None, items=(), skins=()):
    from gw2bot.cogs.misc import Misc

    cog = Misc(_fake_bot(session, users))
    cog.db = gw2_db(items=items, skins=skins)
    return cog


async def wiki(wiki_session, **options):
    """Run /wiki. Returns (what was sent, (url, headers) requested)."""
    from gw2bot.cogs.misc import Misc

    def cog_for(session, users):
        cog = _misc_cog(session, users)
        cog.bot.session = wiki_session
        return cog

    sent, _ = await run_command(cog_for, Misc.wiki, [], permissions=(), **options)
    return sent, wiki_session.requests


async def chatcode(*, items=(), skins=(), **options):
    """Run /chatcode with the cached `items` and `skins`; returns its reply."""
    from gw2bot.cogs.misc import Misc

    sent, _ = await run_command(lambda session, users: _misc_cog(session, users, items, skins),
                                Misc.chatcode, [], permissions=(), **options)
    return sent


async def chatcode_choices(option, text, *, items=(), skins=()):
    """The /chatcode autocomplete for `option` (item, skin or upgrade), as
    (name, value)."""
    cog = _misc_cog(items=items, skins=skins)
    autocomplete = getattr(cog, f"chatcode_{option}_autocomplete")
    return [(c.name, c.value) for c in await autocomplete(MagicMock(), text)]


# --- Guild sync ------------------------------------------------------------------

class FakeGuildsyncs:
    """gw2.guildsyncs: find by guild_id, update_one, count_documents."""

    def __init__(self, docs):
        self.docs = docs
        self.updates = []

    def find(self, query):
        found = [d for d in self.docs if d["guild_id"] == query["guild_id"]]

        async def iterate():
            for doc in found:
                yield doc

        return iterate()

    async def update_one(self, query, update):
        self.updates.append((query, update))


def discord_member(member_id, *, roles=1, days_on_server=3):
    """A server member with `roles` roles (1 is just @everyone)."""
    member = MagicMock(id=member_id, bot=False)
    member.roles = [MagicMock(id=900 + i) for i in range(roles)]
    member.joined_at = datetime.datetime.now(UTC) - datetime.timedelta(days=days_on_server)
    return member


async def run_guildsync(members, accounts, responses, *, syncs=1, purge=True):
    """Run a full guild sync on a server with `members` (see
    discord_member), whose accounts are {member id: account name}, against
    `syncs` guild syncs with tag and rank roles off. `responses` are each
    sync's guild/:id/members (see FakeSession). Returns the ids of the
    members kicked."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.guildwars2.guild import GuildSync

    class Cog(GuildSync, _Harness):
        pass

    users = MemoryUsers({member_id: stored_key(["account", "guilds"], account_name=name)
                         for member_id, name in accounts.items()})
    session = FakeSession(*responses)
    cog = Cog(session, users)
    guild = MagicMock(id=10, chunked=True, members=members)
    guild.kick = AsyncMock()
    guild.get_role = lambda role_id: None
    for member in members:
        member.guild = guild
    docs = [{"_id": f"sync{i}", "guild_id": 10, "gid": f"GUILD-{i}", "key": "LEADER", "rank_roles": {},
             "tag_role": None, "enabled": {"ranks": False, "tag": False}, "name": f"Guild {i}", "tag": "EX"}
            for i in range(syncs)]
    cog.db = SimpleNamespace(guildsyncs=FakeGuildsyncs(docs))
    cog.bot.data.guilds.get = AsyncMock(return_value={"guildsync": {"enabled": True, "purge": purge}})
    await cog.run_guildsyncs(guild)
    return [call.kwargs["user"].id for call in guild.kick.await_args_list]
async def set_event_reminder(**options):
    """Run /reminder event. Returns (reply, users' settings writes)."""
    from gw2bot.cogs.guildwars2.notifiers import NotiifiersMixin

    users = MemoryUsers({1: {}})

    def cog_for(session, _):
        class Cog(NotiifiersMixin, _Harness):
            pass

        cog = Cog(session, users)
        cog.boss_schedule = cog.generate_schedule()
        return cog

    sent, _ = await run_command(cog_for, NotiifiersMixin.reminder_event, [], permissions=(), users=users, **options)
    return sent, users.writes



def _notifier_cog(session=None, users=None):
    from gw2bot.cogs.guildwars2.notifiers import NotiifiersMixin

    class Cog(NotiifiersMixin, _Harness):
        pass

    return Cog(session, users)


async def run_gem_tracker(responses, tracked):
    """One run of the gem tracker. `tracked` is {user id: gemtrack copper};
    users 9xx can't be DMed. Returns (DMs as (user id, text), settings
    writes, anything the run raised)."""
    from unittest.mock import AsyncMock

    import discord

    users = MemoryUsers({user_id: {"gemtrack": price} for user_id, price in tracked.items()})
    cog = _notifier_cog(FakeSession(*responses), users)
    sent = []

    def get_user(user_id):
        user = MagicMock(id=user_id, mention=f"<@{user_id}>")

        async def send(text):
            if user_id >= 900:
                raise discord.Forbidden(MagicMock(status=403), "Cannot send messages to this user")
            sent.append((user_id, text))

        user.send = AsyncMock(side_effect=send)
        return user

    cog.bot.get_user = get_user
    try:
        await type(cog).gem_tracker.coro(cog)
        error = None
    except Exception as e:
        error = e
    return sent, users.writes, error


class MemoryGuilds:
    """bot.data.guilds: server settings by id, find() with equality and
    {"$ne": value} on dotted fields, update() recorded."""

    def __init__(self, docs):
        self.docs = docs
        self.writes = []

    async def get(self, guild_id):
        return self.docs.get(guild_id, {})

    async def update(self, guild_id, fields, op="set"):
        self.writes.append((guild_id, op, fields))

    async def find(self, query=None, **kwargs):
        def value(doc, name):
            for part in name.split("."):
                doc = doc.get(part) if isinstance(doc, dict) else None
            return doc

        def matches(doc, field, condition):
            if isinstance(condition, dict):
                return value(doc, field) != condition["$ne"]
            return value(doc, field) == condition

        for guild_id, doc in list(self.docs.items()):
            if all(matches(doc, f, c) for f, c in (query or {}).items()):
                yield {**doc, "_id": guild_id}


def text_channel(channel_id, guild_id=10, *, can_send=True, can_embed=True):
    """A channel whose sent messages are recorded in channel.sent as
    (content, embed dict or None)."""
    from unittest.mock import AsyncMock

    channel = MagicMock(id=channel_id)
    channel.guild.id = guild_id
    permissions = channel.permissions_for.return_value
    permissions.send_messages = can_send
    permissions.embed_links = can_embed
    permissions.read_message_history = True
    channel.sent = []

    async def send(content=None, *, embed=None, **kwargs):
        channel.sent.append((content, embed.to_dict() if embed else None))
        return MagicMock(id=1000 + len(channel.sent))

    channel.send = AsyncMock(side_effect=send)
    return channel


async def run_news_checker(feed, cached_titles, guilds, channels):
    """One run of the news checker against an RSS `feed` (text). `guilds`
    are server settings by id, `channels` text_channel()s. Returns
    (config writes, server settings writes, anything the run raised)."""
    from unittest.mock import AsyncMock

    cog = _notifier_cog()
    cog.session = FakeWikiSession({"https://www.guildwars2.com/en/feed/": feed})
    cog.bot.data.config.get = AsyncMock(return_value={"cache": {"news": cached_titles}})
    cog.bot.data.config.update = AsyncMock()
    cog.bot.data.guilds = MemoryGuilds(guilds)
    by_id = {c.id: c for c in channels}
    cog.bot.get_channel = by_id.get
    try:
        await type(cog).news_checker.coro(cog)
        error = None
    except Exception as e:
        error = e
    config_writes = [call.args[0] for call in cog.bot.data.config.update.await_args_list]
    return config_writes, cog.bot.data.guilds.writes, error


async def run_game_update_checker(config, build_page):
    """One run of the game update checker with the bot's `config` document
    and `build_page` as the build number page. Returns anything it raised."""
    from unittest.mock import AsyncMock

    cog = _notifier_cog()
    cog.session = FakeWikiSession({"http://assetcdn.101.arenanetworks.com/latest/101": build_page})
    cog.bot.data.config.get = AsyncMock(return_value=config)
    cog.bot.data.config.update = AsyncMock()
    cog.rebuild_database = AsyncMock()
    cog.update_notification = AsyncMock(return_value=None)
    try:
        await type(cog).game_update_checker.coro(cog)
    except Exception as e:
        return e
    return None


async def run_daily_notifier(settings, *, previous_message_exists=True, channel_exists=True, can_send=True,
                             can_embed=True):
    """One 23:40 daily notifier run for a server whose `daily` settings
    are `settings` (channel 5; the previous post is message 999). Returns
    {"sent", "edited", "deleted", "pinned", "unpinned": [message ids],
    "texts": [text-only messages], "embeds": [embeds sent, as dicts],
    "writes": server settings writes}."""
    from unittest.mock import AsyncMock

    import discord

    events = {"sent": [], "edited": [], "deleted": [], "pinned": [], "unpinned": [], "texts": [], "embeds": []}
    messages = {}

    def message(message_id):
        msg = MagicMock(id=message_id, pinned=False)

        async def act(name):
            if message_id in events["deleted"]:
                raise discord.NotFound(MagicMock(status=404), "Unknown Message")
            events[name].append(message_id)

        def recorder(name):
            async def record(*args, **kwargs):
                await act(name)

            return AsyncMock(side_effect=record)

        msg.edit, msg.delete = recorder("edited"), recorder("deleted")
        msg.pin, msg.unpin = recorder("pinned"), recorder("unpinned")
        messages[message_id] = msg
        return msg

    if previous_message_exists:
        message(999)
    channel = MagicMock(id=5)
    channel.guild.id = 10
    permissions = channel.permissions_for.return_value
    permissions.send_messages = can_send
    permissions.embed_links = can_embed
    permissions.read_message_history = True

    async def send(*args, embed=None, **kwargs):
        if embed is None:
            events["texts"].append(args[0])
            return message(0)
        events["embeds"].append(embed.to_dict())
        msg = message(1000 + len(events["sent"]) + 1)
        events["sent"].append(msg.id)
        return msg

    async def fetch_message(message_id):
        if message_id not in messages or message_id in events["deleted"]:
            raise discord.NotFound(MagicMock(status=404), "Unknown Message")
        return messages[message_id]

    async def history(**kwargs):
        return
        yield

    channel.send = AsyncMock(side_effect=send)
    channel.fetch_message = AsyncMock(side_effect=fetch_message)
    channel.history = history

    cog = _daily()
    cog.cache_dailies = AsyncMock()
    cog.bot.data.config.get = AsyncMock(return_value={"cache": {"dailies_tomorrow": {"raids": [], "fractals": []}}})
    cog.bot.data.guilds = MemoryGuilds({10: {"daily": {"on": True, "channel": 5, "categories": ["psna"],
                                                       "message": 999, **settings}}})
    cog.bot.get_channel = {5: channel}.get if channel_exists else {}.get
    await type(cog).send_daily_notifs.coro(cog)
    for _ in range(50):
        await asyncio.sleep(0)
    return {**events, "writes": cog.bot.data.guilds.writes}


async def api_key_role(**options):
    """Run /server api_key_role on server 10. Returns (reply, settings
    writes, whether a sync of the server's roles started)."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.guildwars2.guildmanage import GuildManageMixin

    guilds = MemoryGuilds({})
    cogs = []

    def cog_for(session, users):
        class Cog(GuildManageMixin, _Harness):
            pass

        cog = Cog(session, users)
        cog.bot.data.guilds = guilds
        cog.key_sync_guild = AsyncMock()
        cogs.append(cog)
        return cog

    def in_server(interaction):
        interaction.guild.id = 10

    sent, _ = await run_command(cog_for, GuildManageMixin.server_key_sync, [], permissions=(),
                                on_interaction=in_server, **options)
    return sent, guilds.writes, cogs[0].key_sync_guild.await_count == 1


async def switch_key(stored, token):
    """Run /key switch for a user whose settings are `stored`. Returns
    (reply, settings writes)."""
    from gw2bot.cogs.guildwars2.key import KeyMixin

    users = MemoryUsers({1: stored})

    def cog_for(session, _):
        class Cog(KeyMixin, _Harness):
            pass

        return Cog(session, users)

    sent, _ = await run_command(cog_for, KeyMixin.key_switch, [], permissions=(), users=users, token=token)
    return sent, users.writes


async def can_add_guildsync(existing, in_game_guild_id="NEW"):
    """Whether a server with `existing` guild syncs (in-game guild ids) can
    add one for `in_game_guild_id`."""
    from gw2bot.cogs.guildwars2.guild import GuildSync

    class Syncs:
        async def find_one(self, query):
            return {"gid": query["gid"]} if query["gid"] in existing else None

        async def count_documents(self, query):
            return len(existing)

    class Cog(GuildSync, _Harness):
        pass

    cog = Cog()
    cog.db = SimpleNamespace(guildsyncs=Syncs())
    return await cog.can_add_sync(MagicMock(id=10), in_game_guild_id)



DAILY_CACHE = {
    "fractals": ["Daily Tier 4 Aquatic Ruins", "Daily Recommended Fractal—Scale 25"],
    "raids": ["Raid Bounty: Vale Guardian"],
    "lws3": ["Daily Bitterfrost Frontier Mining Specialist"],
    "lws4": [],
}


def _daily_cog(session=None, users=None, cache=None):
    from unittest.mock import AsyncMock

    cog = daily.Daily(_fake_bot(session, users))
    config = {"cache": {"dailies": cache, "dailies_tomorrow": cache}} if cache is not None else {"cache": {}}
    cog.bot.data.config.get = AsyncMock(return_value=config)
    cog.bot.data.config.update = AsyncMock()
    return cog


async def daily_command(cache, *, now=None, **options):
    """Run /daily with `cache` as the cached rotation (None: not cached),
    optionally with the clock frozen at `now`."""
    import contextlib

    with _at(now) if now else contextlib.nullcontext():
        sent, _ = await run_command(lambda session, users: _daily_cog(session, users, cache), daily.Daily.daily, [],
                                    permissions=(), **options)
    return sent


async def run_dailies_refresh(responses):
    """One run of the dailies refresh against the API `responses`
    (achievements/categories, then achievements). Returns (config writes,
    anything the run raised)."""
    cog = _daily_cog(FakeSession(*responses), cache={})
    try:
        await type(cog).refresh_dailies.coro(cog)
        error = None
    except Exception as e:
        error = e
    return [call.args[0] for call in cog.bot.data.config.update.await_args_list], error


async def notifier_daily(*, choose=None, enabled=True, already_enabled=False, **options):
    """Run /notifier daily on server 10, posting to channel 5, then pick
    the categories in `choose` from its dropdown (None: let it time out).
    Returns (first reply, final message as (content, embed dict or None),
    server settings writes)."""
    from unittest.mock import AsyncMock, patch

    import discord

    from gw2bot.cogs.guildwars2.notifiers import NotiifiersMixin

    guilds = MemoryGuilds({10: {"daily": {"on": already_enabled}}})
    final = []

    async def wait(view):
        if choose is None:
            return True
        dropdown = view.children[0]
        dropdown._values = list(choose)
        interaction = MagicMock()
        interaction.guild.id = 10
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        await dropdown.callback(interaction)
        kwargs = interaction.edit_original_response.await_args.kwargs
        embed = kwargs.get("embed")
        final.append((kwargs.get("content"), embed.to_dict() if embed else None))
        return False

    interactions = []

    def cog_for(session, users):
        class Cog(NotiifiersMixin, _Harness):
            pass

        cog = Cog(session, users)
        cog.bot.data.guilds = guilds
        config = {"cache": {"dailies": DAILY_CACHE, "dailies_tomorrow": DAILY_CACHE}}
        cog.bot.data.config.get = AsyncMock(return_value=config)
        # The example notification comes from the Daily cog
        daily_cog = daily.Daily(cog.bot)
        cog.bot.get_cog = {"Daily": daily_cog}.get
        return cog

    def in_server(interaction):
        interaction.guild.id = 10
        interaction.edit_original_response = AsyncMock()
        interactions.append(interaction)

    channel = MagicMock(id=5, mention="<#5>")
    channel.permissions_for.return_value.send_messages = True
    channel.permissions_for.return_value.embed_links = True
    with patch.object(discord.ui.View, "wait", wait):
        sent, _ = await run_command(cog_for, NotiifiersMixin.daily_notifier, [], permissions=(),
                                    on_interaction=in_server, enabled=enabled,
                                    channel=channel if enabled else None, **options)
    if choose is None and enabled:
        edit = interactions[0].edit_original_response.await_args
        final.append((edit.kwargs.get("content"), None) if edit else None)
    return sent, final[0] if final else None, guilds.writes
