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
from unittest.mock import MagicMock

import time_machine

from gw2bot.cogs.guildwars2 import GuildWars2
from gw2bot.cogs.guildwars2.achievements import AchievementsMixin
from gw2bot.cogs.guildwars2.api import ApiMixin
from gw2bot.cogs.guildwars2.characters import CharactersMixin
from gw2bot.cogs.guildwars2.commerce import CommerceMixin
from gw2bot.cogs.guildwars2 import daily
from gw2bot.cogs.guildwars2.daily import DailyMixin
from gw2bot.cogs.guildwars2.database import DatabaseMixin
from gw2bot.cogs.guildwars2.events import EventsMixin
from gw2bot.cogs.guildwars2.misc import MiscMixin
from gw2bot.cogs.guildwars2.skills import SkillsMixin
from gw2bot.cogs.guildwars2.utils import chat, db
from gw2bot.cogs.guildwars2.wvw import WvwMixin

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "gw2bot" / "cogs" / "guildwars2"
UTC = datetime.timezone.utc


def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


_GAMEDATA = _load("gamedata.json")
_INSTABILITIES = _load("instabilities.json")


class _Harness(
    AchievementsMixin,
    ApiMixin,
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

    def __init__(self, session=None):
        self.gamedata = _GAMEDATA
        self.instabilities = _INSTABILITIES
        self.embed_color = 0xC12D2B
        self.emojis = {}
        self.log = logging.getLogger("tests")
        self.bot = MagicMock()
        self.session = session
        self.api = _client(session) if session is not None else None

    def get_emoji(self, ctx, emoji, *, fallback=False, fallback_fmt="{}", **kwargs):
        return fallback_fmt.format(emoji) if fallback else ""

    async def get_embed_color(self, ctx):
        return self.embed_color


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


class FakeUserDatabase:
    """The bot.database calls behind fetch_key and the rename check."""

    def __init__(self, doc):
        self.doc = doc
        self.writes = []

    async def get_user(self, user, cog=None):
        return self.doc

    async def get(self, user, cog=None):
        return self.doc

    async def set(self, user, settings, cog=None, *, operator="set"):
        self.writes.append((operator, settings))


async def fetch_account(session, stored, user_id=1):
    """Call /account as a user whose stored settings are `stored`.

    Returns (account data, database writes, DMs sent to the user), after
    any background work the call started has finished.
    """
    from unittest.mock import AsyncMock

    harness = _Harness(session)
    harness.bot.database = FakeUserDatabase(stored)
    user = MagicMock(id=user_id)
    user.send = AsyncMock()
    data = await harness.call_api("account", user)
    await asyncio.gather(*getattr(harness, "background_tasks", ()), return_exceptions=True)
    sent = [call.args[0] for call in user.send.await_args_list]
    return data, harness.bot.database.writes, sent


def api_error_message(error):
    """The message shown to the user for an exception from the API layer."""
    interaction = MagicMock()
    return asyncio.run(GuildWars2.cog_error_handler(None, interaction, error))


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
        self.notifier.bot.database.db.gw2.updates = self.updates
        self.pages = pages
        self.notifier.session = FakePageSession(pages)

    async def check(self):
        """[(title, markdown, minor)] for the notes the bot would send."""
        notes = await self.notifier.update_notification("12345") or []
        return [
            (embed.title, embed.fields[0].value, minor) for embed, text, minor in notes
        ]
