"""Adapter between the tests and the code under test.

Tests only call the plain functions in this module (and the fakes it
exports), never cogs directly. When a piece of logic moves, repoint the
matching function here; the tests themselves should not need to change.
The fakes themselves are in the fakes package.
"""
import asyncio
import datetime
import logging
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from fakes.bot import GAMEDATA, at, client, fake_bot, run_command, stored_key  # noqa: F401
from fakes.db import FakeUserRepo, MemoryCollection, MemoryDb, MemorySettings, gw2_db  # noqa: F401
from fakes.http import (  # noqa: F401
    FakeDpsReport,
    FakeImageSession,
    FakePageSession,
    FakeSession,
    FakeWikiSession,
)
from fakes.servers import FakeMember, FakeRole, FakeServer, RecordingChannel, log_file  # noqa: F401
from gw2bot.cogs import daily
from gw2bot.cogs.base import GW2Cog
from gw2bot.utils import chat, db

UTC = datetime.timezone.utc
_GAMEDATA = GAMEDATA


def _shared_cog(session=None, users=None):
    """A cog with only what every cog shares."""
    return GW2Cog(fake_bot(session, users))


# --- Items and coins -------------------------------------------------------

def chat_code(item_id, count=1, skin_id=None, upgrades=()):
    from gw2bot.cogs.misc import generate_chat_code

    return generate_chat_code(item_id, count, skin_id, list(upgrades))


def format_coins(copper):
    return _shared_cog().gold_to_coins(None, copper)


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
    return _events_cog().format_timedelta(td)


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
        cog = Skills(fake_bot(session, users))
        cog.db = gw2_db(skills=skills, traits=traits)
        return cog

    sent, _ = await run_command(cog_for, handler, [], permissions=(), pages=pages, head_error=head_error, **options)
    return sent, sessions[0].heads


async def skill_search(command, text, *, skills=(), traits=()):
    """The /skill or /trait autocomplete choices for `text`, as (name, value)."""
    from gw2bot.cogs.skills import Skills

    cog = Skills(fake_bot())
    cog.db = gw2_db(skills=skills, traits=traits)
    autocomplete = {"skill": cog.skill_autocomplete, "trait": cog.trait_autocomplete}[command]
    return [(c.name, c.value) for c in await autocomplete(MagicMock(), text)]


# --- Dailies (all evaluated as of noon UTC on `date`) ----------------------

def _daily():
    return daily.Daily(fake_bot())


def year_day(date):
    with at(date):
        return _daily().get_year_day(tomorrow=False)


def daily_rotation(categories, names):
    return daily.daily_rotation(categories, names)


def daily_categories(saved):
    return daily.normalize_categories(saved)


def daily_fields(categories, cache, now, tomorrow=False):
    """[(name, value)] of the daily embed, given the cached rotation."""
    harness = _daily()
    doc = {"cache": {"dailies": cache, "dailies_tomorrow": cache}}
    with at(now):
        embed = asyncio.run(harness.daily_embed(categories, doc=doc, tomorrow=tomorrow))
    return [(f.name, f.value) for f in embed.fields]


def pact_supply_agents(date):
    with at(date):
        return _daily().get_psna()


def instabilities(fractal_level, date):
    with at(date):
        names = _daily().get_instabilities(fractal_level, tomorrow=False)
    return names.split("\n") if names is not None else None


def cm_instabilities(date):
    """{CM fractal name: [instability names]}."""
    with at(date):
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

    choices = asyncio.run(Wvw(fake_bot()).team_autocomplete(None, current))
    return [(c.name, c.value) for c in choices]


async def wvw_info(responses, *, permissions=("account",), **options):
    """Run /wvw info; `responses`: account (without a team option), then
    wvw/matches."""
    from gw2bot.cogs.wvw import Wvw

    def cog_for(session, users):
        return Wvw(fake_bot(session, users))

    return await run_command(cog_for, Wvw.wvw_info, responses, permissions=permissions, **options)


# --- Event timers ----------------------------------------------------------

def upcoming_bosses(now, limit=8):
    """[(boss name, datetime)] for the next `limit` world bosses."""
    with at(now):
        bosses = _events_cog().get_upcoming_bosses(limit)
    return [
        (b["name"], datetime.datetime.fromtimestamp(int(b["time"][3:-3]), UTC))
        for b in bosses
    ]


def seconds_until_boss(name, now):
    with at(now):
        return _events_cog().get_time_until_event({"type": "boss", "name": name})


def seconds_until_phase(group, map_name, phase, now):
    reminder = {"type": "event", "group": group, "map_name": map_name, "name": phase}
    with at(now):
        return _events_cog().get_time_until_event(reminder)


def timer_titles():
    """{group: title} for every event-timer group in the game data."""
    groups = [g for g in _GAMEDATA["event_timers"] if g != "bosses"]
    titles = {}
    for group in groups:
        embed = asyncio.run(_events_cog().timer_embed(None, group))
        titles[group] = embed.title
    return titles


def timer_state(group, now):
    """{map name: (current phase or None, next phase, datetime of next phase)}."""
    with at(now):
        embed = asyncio.run(_events_cog().timer_embed(None, group))
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

async def api_get(session, endpoint, key=None, schema=None):
    """GET through the bot's GW2 API client, using `session` for HTTP."""
    return await client(session).get(endpoint, key=key, schema=schema)


async def api_get_many(session, endpoints, key=None):
    return await client(session).get_many(endpoints, key=key)


async def fetch_account(session, stored, user_id=1):
    """Call /account as a user whose stored settings are `stored`.

    Returns (account data, database writes, DMs sent to the user), after
    any background work the call started has finished.
    """
    from unittest.mock import AsyncMock

    users = FakeUserRepo(stored)
    harness = _shared_cog(session, users)
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

class UpdateNotesChecker:
    """Runs the update-notes check against a fake forum, keeping state
    (sent counts, blocked flag) between checks like the running bot does."""

    def __init__(self, pages):
        from gw2bot.cogs.notifiers import Notifiers

        self.notifier = Notifiers(MagicMock())
        self.notifier.log = logging.getLogger("tests.update_notes")
        self.updates = MemoryCollection()
        self.notifier.bot.data.gw2.updates = self.updates
        self.pages = pages
        self.notifier.bot.session = FakePageSession(pages)

    async def check(self):
        """[(title, markdown, minor)] for the notes the bot would send."""
        notes = await self.notifier.update_notification("12345") or []
        return [
            (embed.title, embed.fields[0].value, minor) for embed, text, minor in notes
        ]


# --- Settings commands ------------------------------------------------------

class SettingsCommands:
    """Runs server/channel settings commands against in-memory settings,
    which survive a simulated restart."""

    def __init__(self):
        self.guilds = MemorySettings()
        self.channels = MemorySettings()
        self.start()

    def start(self):
        """(Re)create the cog, as after a restart: in-memory caches are lost."""
        from unittest.mock import AsyncMock

        from gw2bot.cogs.chatlinks import ChatLinks
        from gw2bot.cogs.evtc import Evtc
        from gw2bot.cogs.server import Server

        bot = MagicMock()
        bot.data.guilds = self.guilds
        bot.data.channels = self.channels
        self.cog = Server(bot)
        self.cog.force_guild_account_names = AsyncMock()
        self.evtc = Evtc(bot)
        self.previews = ChatLinks(bot)
        bot.get_cog = {"ChatLinks": self.previews}.get

    async def load(self):
        await self.previews.cog_load()

    def previews_disabled(self):
        """Servers whose chat link previews are off, as the previews see it."""
        return self.previews.previews_disabled

    async def run(self, command, guild_id=10, **options):
        """The reply to running `command` (a method name) in a guild."""
        from unittest.mock import AsyncMock

        interaction = MagicMock()
        interaction.guild.id = guild_id
        interaction.response.send_message = AsyncMock()
        cog = self.cog if hasattr(type(self.cog), command) else self.evtc
        await getattr(type(cog), command).callback(cog, interaction, **options)
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

        from gw2bot.cogs.evtc import Evtc

        self.channels = MemorySettings()
        self.cog = Evtc(MagicMock())
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


class EvtcApiKeys:
    """Runs /evtc api_key against an in-memory key collection."""

    def __init__(self):
        from gw2bot.cogs.evtc import Evtc

        self.keys = MemoryCollection()
        self.cog = Evtc(MagicMock())
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

async def pvp(command, stats, *, rank_icon="https://render/rank.png", permissions=("account", "pvp"), **options):
    """Run /pvp stats or /pvp professions against synthetic pvp/stats."""
    responses = [(200, stats)]
    if command == "stats":
        responses.append((200, {"id": 1, "icon": rank_icon}))
    from gw2bot.cogs.pvp import Pvp

    handler = {"stats": Pvp.pvp_stats, "professions": Pvp.pvp_professions}[command]

    def cog_for(session, users):
        return Pvp(fake_bot(session, users))

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
        return WizardsVault(fake_bot(session, users))

    with at(now):
        return await run_command(cog_for, WizardsVault.wizards_vault, responses, permissions=permissions)


async def commerce(command, responses, *, items=(), permissions=("account", "tradingpost"), users=None, **options):
    """Run a /tp or /gem command; `items` are the cached item documents."""
    from gw2bot.cogs.commerce import Commerce

    handler = getattr(Commerce, command)

    def cog_for(session, users):
        cog = Commerce(fake_bot(session, users))
        cog.db = gw2_db(items=items)
        return cog

    return await run_command(cog_for, handler, responses, permissions=permissions, users=users, **options)


async def tp_item_search(text, items):
    """The /tp price autocomplete choices for `text`, as (name, value)."""
    from gw2bot.cogs.commerce import Commerce

    cog = Commerce(fake_bot())
    cog.db = gw2_db(items=items)
    choices = await Commerce.tp_autocomplete(cog, MagicMock(), text)
    return [(c.name, c.value) for c in choices]


async def achievement(responses, achievement_name, *, db, permissions=("account", "progression")):
    """Run /achievement with the cached game data in `db` (see gw2_db)."""
    from gw2bot.cogs.achievements import Achievements

    def cog_for(session, users):
        cog = Achievements(fake_bot(session, users))
        cog.db = db
        return cog

    return await run_command(
        cog_for, Achievements.achievementinfo, responses, permissions=permissions,
        achievement_name=achievement_name,
    )


async def achievement_search(text, db):
    """The /achievement autocomplete choices for `text`, as (name, value)."""
    from gw2bot.cogs.achievements import Achievements

    cog = Achievements(fake_bot())
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
        cog = Wallet(fake_bot(session, users))
        cog.db = gw2_db(currencies=currencies, items=items)
        return cog

    with patch("random.random", return_value=random_value):
        return await run_command(cog_for, Wallet.wallet, responses, permissions=permissions, **options)


async def items_in_account(responses, item_ids, *, permissions=("account", "inventories", "characters"), **options):
    """GW2Cog.find_items_in_account: `responses` are account/bank,
    account/inventory, account/materials, characters (and
    commerce/delivery with the tradingpost permission)."""
    session = FakeSession(*responses)
    cog = _shared_cog(session, FakeUserRepo(stored_key(permissions)))
    user = MagicMock(id=1)
    result = await cog.find_items_in_account(user, item_ids, **options)
    # Plain dicts, for comparing
    if options.get("flatten"):
        return dict(result)
    return {item: dict(places) for item, places in result.items()}


def _account_cog(session=None, users=None, db=None, raids=None):
    from unittest.mock import AsyncMock

    from gw2bot.cogs.account import Account

    cog = Account(fake_bot(session, users))
    cog.db = db or gw2_db()
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

    with at(now) if now else contextlib.nullcontext():
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

    cog = Characters(fake_bot(session, users))
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

    with at(now) if now else contextlib.nullcontext():
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
    with at(now):
        choices = await cog.character_autocomplete(interaction, current)
        for _ in range(10):
            await asyncio.sleep(0)
    return [c.name for c in choices], users.writes, [(url, params) for url, params, _ in session.requests]


# --- Guilds --------------------------------------------------------------------

async def guild_command(command, responses, *, permissions=("account", "guilds"), items=(), users=None,
                        discord_members=None, **options):
    """Run /guild <command>. `users` are other users' settings by Discord
    id (the caller is id 1); `discord_members` the Discord server's members
    by id, as {id: mention}, or None to run it in DMs."""
    from gw2bot.cogs.guild import Guild

    handler = getattr(Guild, "guild_" + command)
    repo = MemorySettings({1: stored_key(permissions), **(users or {})})

    def cog_for(session, _):
        cog = Guild(fake_bot(session, repo))
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
    cog = _shared_cog(session, users)
    interaction = MagicMock()
    interaction.user.id = 1
    interaction.command.binding = cog
    cog.bot.data.guilds.get = AsyncMock(return_value={"guild_ingame": server_default} if server_default else {})
    with at(now):
        choices = await guild_name_autocomplete(interaction, current)
        for _ in range(10):
            await asyncio.sleep(0)
    return ([(c.name, c.value) for c in choices], users.writes,
            [(url, params) for url, params, _ in session.requests])



# --- Misc -------------------------------------------------------------------------

def _misc_cog(session=None, users=None, items=(), skins=()):
    from gw2bot.cogs.misc import Misc

    cog = Misc(fake_bot(session, users))
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

async def set_event_reminder(**options):
    """Run /reminder event. Returns (reply, users' settings writes)."""
    from gw2bot.cogs.events import Events

    users = MemorySettings({1: {}})
    sent, _ = await run_command(lambda session, _: _events_cog(session, users), Events.reminder_event, [],
                                permissions=(), users=users, **options)
    return sent, users.writes



def _notifier_cog(session=None, users=None):
    from gw2bot.cogs.notifiers import Notifiers

    return Notifiers(fake_bot(session, users))


async def run_gem_tracker(responses, tracked):
    """One run of the gem tracker. `tracked` is {user id: gemtrack copper};
    users 9xx can't be DMed. Returns (DMs as (user id, text), settings
    writes, anything the run raised)."""
    from unittest.mock import AsyncMock

    import discord

    users = MemorySettings({user_id: {"gemtrack": price} for user_id, price in tracked.items()})
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


async def run_news_checker(feed, cached_titles, guilds, channels):
    """One run of the news checker against an RSS `feed` (text). `guilds`
    are server settings by id, `channels` RecordingChannels. Returns
    (config writes, server settings writes, anything the run raised)."""
    from unittest.mock import AsyncMock

    cog = _notifier_cog()
    cog.bot.session = FakeWikiSession({"https://www.guildwars2.com/en/feed/": feed})
    cog.bot.data.config.get = AsyncMock(return_value={"cache": {"news": cached_titles}})
    cog.bot.data.config.update = AsyncMock()
    cog.bot.data.guilds = MemorySettings(guilds)
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
    return (await check_game_updates(config, build_page))["error"]


async def check_game_updates(config, build_page, *, notes=None, servers=None, channels=()):
    """One run of the game update checker. `notes` are what the update
    notes check finds, [(embed, text, minor)]; `servers` settings by id,
    `channels` RecordingChannels. Returns {"error", "rebuilt", "config"
    (writes)}."""
    from unittest.mock import AsyncMock

    cog = _notifier_cog()
    cog.bot.session = FakeWikiSession({"http://assetcdn.101.arenanetworks.com/latest/101": build_page})
    cog.bot.data.config.get = AsyncMock(return_value=config)
    cog.bot.data.config.update = AsyncMock()
    cog.bot.data.guilds = MemorySettings(servers or {})
    cog.bot.get_channel = {c.id: c for c in channels}.get
    cache = MagicMock()
    cache.rebuild_database = AsyncMock()
    cog.bot.get_cog = {"Cache": cache}.get
    cog.update_notification = AsyncMock(return_value=notes)
    try:
        await type(cog).game_update_checker.coro(cog)
        error = None
    except Exception as e:
        error = e
    return {
        "error": error,
        "rebuilt": cache.rebuild_database.await_count == 1,
        "config": [call.args[0] for call in cog.bot.data.config.update.await_args_list],
    }


async def notifier_command(command, *, settings=None, channel=None, **options):
    """Run /notifier news, update or bosses on server 10 with its saved
    `settings`. `channel` is a RecordingChannel (or None). Returns (reply,
    server settings writes)."""
    from gw2bot.cogs.notifiers import Notifiers

    handler = {"news": Notifiers.newsfeed, "update": Notifiers.updatenotifier,
               "bosses": Notifiers.bossnotifier}[command]
    guilds = MemorySettings({10: settings or {}})

    def cog_for(session, users):
        cog = _notifier_cog(session, users)
        cog.bot.data.guilds = guilds
        return cog

    def in_server(interaction):
        interaction.guild.id = 10

    if channel is not None:
        channel.mention = f"<#{channel.id}>"
    sent, _ = await run_command(cog_for, handler, [], permissions=(), on_interaction=in_server, channel=channel,
                                **options)
    return sent, guilds.writes


async def api_key_role(**options):
    """Run /server api_key_role on server 10. Returns (reply, settings
    writes, whether a sync of the server's roles started)."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.server import Server

    guilds = MemorySettings({})
    cogs = []

    def cog_for(session, users):
        cog = Server(fake_bot(session, users))
        cog.bot.data.guilds = guilds
        # The role sync is the Keys cog's
        keys = MagicMock()
        keys.key_sync_guild = AsyncMock()
        cog.bot.get_cog = {"Keys": keys}.get
        cogs.append(keys)
        return cog

    def in_server(interaction):
        interaction.guild.id = 10

    sent, _ = await run_command(cog_for, Server.server_key_sync, [], permissions=(),
                                on_interaction=in_server, **options)
    return sent, guilds.writes, cogs[0].key_sync_guild.await_count == 1


async def switch_key(stored, token):
    """Run /key switch for a user whose settings are `stored`. Returns
    (reply, settings writes)."""
    from gw2bot.cogs.keys import Keys

    users = MemorySettings({1: stored})
    sent, _ = await run_command(lambda session, _: Keys(fake_bot(session, users)), Keys.key_switch, [],
                                permissions=(), users=users, token=token)
    return sent, users.writes


async def can_add_guildsync(existing, in_game_guild_id="NEW"):
    """Whether a server with `existing` guild syncs (in-game guild ids) can
    add one for `in_game_guild_id`."""
    from gw2bot.cogs.guildsync import GuildSync

    cog = GuildSync(fake_bot())
    cog.db = gw2_db(guildsyncs=[{"guild_id": 10, "gid": gid} for gid in existing])
    return await cog.can_add_sync(MagicMock(id=10), in_game_guild_id)



DAILY_CACHE = {
    "fractals": ["Daily Tier 4 Aquatic Ruins", "Daily Recommended Fractal—Scale 25"],
    "raids": ["Raid Bounty: Vale Guardian"],
    "lws3": ["Daily Bitterfrost Frontier Mining Specialist"],
    "lws4": [],
}


def _daily_cog(session=None, users=None, cache=None):
    from unittest.mock import AsyncMock

    cog = daily.Daily(fake_bot(session, users))
    config = {"cache": {"dailies": cache, "dailies_tomorrow": cache}} if cache is not None else {"cache": {}}
    cog.bot.data.config.get = AsyncMock(return_value=config)
    cog.bot.data.config.update = AsyncMock()
    return cog


async def daily_command(cache, *, now=None, **options):
    """Run /daily with `cache` as the cached rotation (None: not cached),
    optionally with the clock frozen at `now`."""
    import contextlib

    with at(now) if now else contextlib.nullcontext():
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

    from gw2bot.cogs.notifiers import Notifiers

    guilds = MemorySettings({10: {"daily": {"on": already_enabled}}})
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
        cog = _notifier_cog(session, users)
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
        sent, _ = await run_command(cog_for, Notifiers.daily_notifier, [], permissions=(),
                                    on_interaction=in_server, enabled=enabled,
                                    channel=channel if enabled else None, **options)
    if choose is None and enabled:
        edit = interactions[0].edit_original_response.await_args
        final.append((edit.kwargs.get("content"), None) if edit else None)
    return sent, final[0] if final else None, guilds.writes



# --- Event timers and reminders -------------------------------------------------

def _events_cog(session=None, users=None):
    from gw2bot.cogs.events import Events

    return Events(fake_bot(session, users))


async def run_reminder(reminder, now, *, existing=()):
    """process_reminder for user 1's first reminder at `now`. Returns (the
    user's DMs as a RecordingChannel, users' settings writes)."""
    dms = RecordingChannel(existing=existing)
    dms.mention = "<@1>"
    users = MemorySettings({1: {"event_reminders": [reminder]}})
    with at(now):
        cog = _events_cog(users=users)
        await cog.process_reminder(SimpleNamespace(id=1, send=dms.send, fetch_message=dms.fetch_message),
                                   dict(reminder), 0)
    return dms, users.writes


async def press_unsubscribe(message_id):
    """Press a reminder DM's Unsubscribe button. Returns (reply, settings
    writes, whether the DM was deleted)."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.events import EventTimerReminderUnsubscribeView

    users = MemorySettings({1: {}})
    cog = _events_cog(users=users)
    view = EventTimerReminderUnsubscribeView(cog)
    interaction = MagicMock()
    interaction.user.id = 1
    interaction.message.id = message_id
    interaction.message.delete = AsyncMock()
    interaction.response.send_message = AsyncMock()
    button = next(item for item in view.children if item.custom_id == "et:unsubscribe")
    await button.callback(interaction)
    return (interaction.response.send_message.await_args.args[0], users.writes,
            interaction.message.delete.await_count == 1)


async def run_boss_notifier(servers, channels, now):
    """One boss notifier run at `now` (the run first sleeps until the next
    boss; that sleep is skipped). `servers` are settings by server id,
    `channels` RecordingChannels. Returns server settings writes."""
    from unittest.mock import patch

    guilds = MemorySettings(servers)
    with at(now):
        cog = _events_cog()
        cog.bot.data.guilds = guilds
        cog.bot.get_channel = {c.id: c for c in channels}.get

        async def no_sleep(delay):
            pass

        with patch.object(asyncio, "sleep", no_sleep):
            await type(cog).boss_notifier.coro(cog)
    return guilds.writes


async def et_command(category, now):
    """Run /et at `now`; returns the embed."""
    from gw2bot.cogs.events import Events

    with at(now):
        sent, _ = await run_command(lambda session, users: _events_cog(session, users), Events.et, [],
                                    permissions=(), category=category)
    return sent



# --- Chat link previews ------------------------------------------------------------

def link(header, *values):
    """A chat link: the type byte, then 4-byte little-endian ids."""
    import base64
    import struct

    data = bytes([header]) + b"".join(struct.pack("<I", v) for v in values)
    return "[&" + base64.b64encode(data).decode() + "]"


async def post_chat_link(content, *, db=None, in_guild=True, opted_out=False, author_is_bot=False, pages=(),
                         can_use_emojis=False):
    """Post a message with `content` where the chat link previewer sees it.
    `db` is the game data cache (see gw2_db). Returns (previews sent as
    (embed dict, replied to the message), link_previews counts added)."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.chatlinks import ChatLinks

    session = FakeSession((500, {}), pages=pages)
    cog = ChatLinks(fake_bot(session))
    cog.db = db or gw2_db()
    cog.previews_disabled = {10} if opted_out else set()
    cog.bot.user.display_avatar.url = "https://cdn/bot.png"
    cog.bot.data.statistics.update_one = AsyncMock()
    message = MagicMock(content=content)
    message.author.bot = author_is_bot
    message.author.display_name = "Example"
    message.author.display_avatar.url = "https://cdn/example.png"
    if in_guild:
        message.guild.id = 10
    else:
        message.guild = None
    permissions = message.channel.permissions_for.return_value
    permissions.read_message_history = True
    permissions.external_emojis = can_use_emojis
    message.channel.send = AsyncMock()
    await type(cog).find_chatcodes(cog, message)
    sent = [(call.kwargs["embed"].to_dict(), call.kwargs.get("reference") is message)
            for call in message.channel.send.await_args_list]
    counted = [call.args[1]["$inc"] for call in cog.bot.data.statistics.update_one.await_args_list]
    return sent, counted



# --- EVTC ---------------------------------------------------------------------------------

def _evtc_cog(session=None, users=None, *, dps_report=None, encounters=(), destinations=(), notifications=(),
              api_keys=()):
    from gw2bot.cogs.evtc import Evtc

    cog = Evtc(fake_bot(session, users))
    cog.bot.session = dps_report
    cog.bot.user.display_avatar.url = "https://cdn/bot.png"
    cog.bot.data.channels = MemorySettings()
    cog.db = SimpleNamespace(
        encounters=MemoryCollection(encounters),
        evtc=SimpleNamespace(destinations=MemoryCollection(destinations),
                             notifications=MemoryCollection(notifications),
                             api_keys=MemoryCollection(api_keys)),
    )
    return cog


async def upload_logs(files, dps_report, *, stored=None, encounters=(), anonymous=False):
    """Process `files` as uploaded by user 1 (whose settings are
    `stored`). Returns (messages sent as (content, embed dict or None), the
    cog's collections, user settings writes)."""
    users = MemorySettings({1: stored or {}})
    cog = _evtc_cog(users=users, dps_report=dps_report, encounters=encounters)
    destination = RecordingChannel()
    await cog.process_evtc(files, SimpleNamespace(id=1), destination, anonymous=anonymous)
    return [(content, embed) for content, embed, _ in destination.sent], cog.db, users.writes


async def evtc_command(file, dps_report, **options):
    """Run /evtc with `file`. Returns what was sent."""
    from gw2bot.cogs.evtc import Evtc

    def cog_for(session, users):
        return _evtc_cog(session, users, dps_report=dps_report)

    sent, _ = await run_command(cog_for, Evtc.evtc, [], permissions=(), file=file, **options)
    return sent


async def run_evtc_autopost(notifications, destinations, reports, channels, *, members=None):
    """One run of the EVTC autopost loop. `channels` are RecordingChannels;
    `members` are {channel id: [user ids on that server]} (default: the
    user is everywhere). Returns the notifications afterwards."""
    from unittest.mock import AsyncMock

    cog = _evtc_cog(dps_report=FakeDpsReport(reports), destinations=destinations, notifications=notifications)
    by_id = {c.id: c for c in channels}
    for channel in channels:
        on_server = (members or {}).get(channel.id)
        channel.guild.chunked = True
        channel.guild.chunk = AsyncMock()
        channel.guild.get_member = (
            lambda user_id, on_server=on_server: MagicMock(id=user_id)
            if on_server is None or user_id in on_server else None
        )
    cog.bot.get_channel = by_id.get
    cog.bot.get_user = lambda user_id: SimpleNamespace(id=user_id, name="example", discriminator="0")
    await type(cog).post_evtc_notifications.coro(cog)
    return cog.db.evtc.notifications.docs


async def evtc_destination_command(command, *, api_key=True, destinations=(), account=None, guilds=(),
                                   choose=None, channels=None):
    """Run /evtc_automation autopost add_destination (in channel 5) or
    remove_destinations. For adding, `choose` picks guild ids from its
    dropdown, "next" skips it, None lets it time out. For removing,
    `choose` picks destinations by index. Returns (replies, destinations
    afterwards)."""
    from unittest.mock import AsyncMock, patch

    import discord

    from gw2bot.cogs.evtc import Evtc

    handler = {"add": Evtc.evtc_autoupload_add, "remove": Evtc.evtc_autoupload_remove}[command]
    replies = []
    cogs = []
    responses = [(200, account or {"name": "Example.1234", "guilds": [g["id"] for g in guilds]})]
    responses += [(200, g) for g in guilds]

    def cog_for(session, users):
        keys = [{"user": 1, "token": "EVTC-KEY"}] if api_key else []
        cog = _evtc_cog(session, users, destinations=destinations, api_keys=keys)
        cog.bot.get_channel = (channels or {}).get
        cogs.append(cog)
        return cog

    async def wait(view):
        if choose is None:
            return True
        select = next(item for item in view.children if isinstance(item, discord.ui.Select))
        interaction = MagicMock()
        interaction.response.edit_message = AsyncMock()
        if choose == "next":
            button = next(item for item in view.children if isinstance(item, discord.ui.Button))
            await button.callback(interaction)
        else:
            select._values = [str(c) for c in choose]
            await select.callback(interaction)
        replies.append(interaction.response.edit_message.await_args.kwargs["content"])
        return False

    interactions = []

    def in_channel(interaction):
        interaction.channel.id = 5
        interactions.append(interaction)

    with patch.object(discord.ui.View, "wait", wait):
        sent, _ = await run_command(cog_for, handler, responses, permissions=("account", "guilds"),
                                    on_interaction=in_channel)
    if command == "remove" and choose is not None:
        # The menu isn't waited on: pick from the one that was sent
        view = interactions[0].followup.send.await_args.kwargs["view"]
        select = view.children[0]
        select._values = [str(c) for c in choose]
        interaction = MagicMock()
        interaction.response.edit_message = AsyncMock()
        await select.callback(interaction)
        replies.append(interaction.response.edit_message.await_args.kwargs["content"])
    return [sent] + replies, cogs[0].db.evtc.destinations.docs


# --- Game data cache ----------------------------------------------------------------

def _cache_cog(session=None):
    from unittest.mock import AsyncMock

    from gw2bot.cogs.cache import Cache

    cog = Cache(fake_bot(session))
    cog.db = MemoryDb()
    cog.bot.data.config.update = AsyncMock()
    cog.bot.change_presence = AsyncMock()
    return cog


async def cache_endpoint(responses, endpoint, all_at_once=False):
    """Cache `endpoint` from the API `responses`. Returns ({_id: doc}
    written, API requests)."""
    session = FakeSession(*responses)
    cog = _cache_cog(session)
    await cog.cache_endpoint(endpoint, all_at_once)
    docs = {doc["_id"]: doc for doc in cog.db[endpoint.replace("/", "_")].docs}
    return docs, [url for url, _, _ in session.requests]


async def cache_raids(responses):
    """Returns the config writes."""
    cog = _cache_cog(FakeSession(*responses))
    await cog.cache_raids()
    return [call.args[0] for call in cog.bot.data.config.update.await_args_list]


async def cache_pois(responses):
    """Returns the points of interest written, {_id: doc}."""
    cog = _cache_cog(FakeSession(*responses))
    await cog.cache_pois()
    return {doc["_id"]: doc for doc in cog.db.pois.docs}


async def rebuild_cache(*, failing=(), owner_cached=True):
    """Rebuild the cache with each endpoint's caching faked; those in
    `failing` raise. Returns {"presence": [change_presence kwargs],
    "dms": owner DMs, "cached": endpoints cached, "indexes": {collection:
    [fields]}, "error": anything raised}."""
    from unittest.mock import AsyncMock

    cog = _cache_cog()
    cached = []

    async def cache_endpoint(endpoint, all_at_once=False):
        if endpoint in failing:
            raise ValueError("API down")
        cached.append(endpoint)

    cog.cache_endpoint = cache_endpoint
    cog.cache_raids = AsyncMock()
    cog.cache_pois = AsyncMock()
    owner = MagicMock()
    owner.send = AsyncMock()
    cog.bot.get_user = lambda user_id: owner if owner_cached else None
    cog.bot.fetch_user = AsyncMock(return_value=owner)
    try:
        await cog.rebuild_database()
        error = None
    except Exception as e:
        error = e
    presence = [call.kwargs for call in cog.bot.change_presence.await_args_list]
    return {
        "presence": [{k: str(v) for k, v in p.items()} for p in presence],
        "dms": [call.args[0] for call in owner.send.await_args_list],
        "cached": cached,
        "indexes": {name: c.indexes for name, c in cog.db.collections.items() if c.indexes},
        "error": error,
    }


# --- API keys --------------------------------------------------------------------------------

def api_key(token, account="Example.1234", name="", permissions=("account", "characters")):
    return {"key": token, "account_name": account, "name": name, "permissions": list(permissions)}


async def key_command(command, stored, responses=(), *, in_guild=False, **options):
    """Run /key add, remove, switch or info for user 1 with settings
    `stored`. Returns (reply, settings writes, the other cogs' syncs run
    for the user: ["guildsync", "key role"])."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.keys import Keys

    handler = getattr(Keys, "key_" + command)
    users = MemorySettings({1: stored})
    syncs = []

    def cog_for(session, _):
        cog = Keys(fake_bot(session, users))

        async def guildsync(member):
            syncs.append("guildsync")

        async def key_role(member, role=None):
            syncs.append("key role")

        guild_sync = SimpleNamespace(guildsync_on_member_join=guildsync)
        cog.bot.get_cog = {"GuildSync": guild_sync}.get
        cog.key_sync_user = key_role
        return cog

    def where(interaction):
        if not in_guild:
            interaction.guild = None

    sent, _ = await run_command(cog_for, handler, list(responses) or [(500, {})], permissions=(), users=users,
                                on_interaction=where, **options)
    return sent, users.writes, syncs


async def key_choices(stored, current=""):
    """The key autocomplete for a user with settings `stored`, as (name, value)."""
    from gw2bot.cogs.keys import Keys

    cog = Keys(fake_bot(None, MemorySettings({1: stored})))
    interaction = MagicMock()
    interaction.user.id = 1
    return [(c.name, c.value) for c in await cog.key_autocomplete(interaction, current)]


# --- A Discord server for guild sync ------------------------------------------------------

def guildsync_doc(gid="GUILD-A", *, ranks=True, tag=True, rank_roles=None, tag_role=None, key="LEADER", **extra):
    """A saved guild sync for server 10."""
    return {"guild_id": 10, "gid": gid, "key": key, "rank_roles": rank_roles or {}, "tag_role": tag_role,
            "enabled": {"ranks": ranks, "tag": tag}, "name": "Alpha Guild", "tag": "A", **extra}


def _guildsync_cog(server, users, responses, syncs, *, settings=None, prompts=()):
    from unittest.mock import AsyncMock

    from gw2bot.cogs.guildsync import GuildSync

    session = FakeSession(*(responses or [(500, {})]))
    cog = GuildSync(fake_bot(session, MemorySettings(users)))
    cog.db = gw2_db(guildsyncs=syncs, guildsync_prompts=prompts)
    guilds = MemorySettings({server.id: settings if settings is not None else {"guildsync": {"enabled": True}}})
    cog.bot.data.guilds = guilds
    cog.bot.get_guild = {server.id: server}.get
    cog.bot.wait_until_ready = AsyncMock()
    return cog, session


def accounts(*names):
    """A user's settings with a key per account name."""
    keys = [{"key": f"KEY-{n}", "account_name": n, "name": "", "permissions": ["account", "guilds"]} for n in names]
    return {"key": keys[0], "keys": keys} if keys else {}


async def sync_server(server, users, responses, syncs, **options):
    """A full guild sync of `server`. `users` are settings by member id
    (see accounts), `responses` each sync's guild/:id/ranks (if ranks are
    on) and guild/:id/members in turn. Returns (the syncs afterwards, API
    requests)."""
    cog, session = _guildsync_cog(server, users, responses, syncs, **options)
    await cog.run_guildsyncs(server)
    return cog.db.guildsyncs.docs, [url for url, _, _ in session.requests]


async def member_joins_synced_server(server, member, users, responses, syncs):
    """A member joins `server`; returns the API requests made."""
    cog, session = _guildsync_cog(server, users, responses, syncs)
    await cog.guildsync_on_member_join(member)
    return [url for url, _, _ in session.requests]


async def run_guild_synchronizer(server, users, responses, syncs, *, settings=None):
    """One run of the 60-second guild sync loop."""
    cog, session = _guildsync_cog(server, users, responses, syncs, settings=settings)
    await type(cog).guild_synchronizer.coro(cog)
    return [url for url, _, _ in session.requests]


async def guildsync_command(command, server, *, users=None, responses=(), syncs=(), settings=None, confirm=None,
                            **options):
    """Run /guildsync add, edit, toggle, purge or diagnose (user 1, an admin
    of `server`). `confirm` answers the purge confirmation (None: time out).
    Returns {"replies": every message sent, "syncs": the syncs afterwards,
    "settings": server settings writes, "prompts": authorization prompts
    saved, "requests": API requests}."""
    from unittest.mock import AsyncMock, patch

    import discord

    from gw2bot.cogs.guildsync import GuildSync

    handler = {"add": GuildSync.guildsync_add, "edit": GuildSync.guildsync_edit, "toggle": GuildSync.sync_toggle,
               "purge": GuildSync.sync_purge, "diagnose": GuildSync.guildsync_diagnose}[command]
    cogs = []
    replies = []

    def cog_for(session, _):
        cog, _ = _guildsync_cog(server, users or {}, None, syncs, settings=settings)
        cog.bot.gw2api = client(session)
        cogs.append(cog)
        return cog

    def admin(interaction):
        interaction.guild = server
        interaction.user.name = "admin"
        interaction.user.guild = server
        interaction.edit_original_response = AsyncMock()
        cogs[0].interaction = interaction

    async def wait(view):
        if confirm is None:
            return True
        button = view.children[0 if confirm else 1]
        press = MagicMock()
        press.response.send_message = AsyncMock()
        await button.callback(press)
        return False

    with patch.object(discord.ui.View, "wait", wait):
        sent, requests = await run_command(cog_for, handler, list(responses) or [(500, {})], permissions=(),
                                           users=MemorySettings(users or {}), on_interaction=admin, **options)
    interaction = cogs[0].interaction
    for mock in (interaction.response.send_message, interaction.followup.send):
        for call in mock.await_args_list:
            embed = call.kwargs.get("embed")
            replies.append(embed.to_dict() if embed else (call.args[0] if call.args else call.kwargs.get("content")))
    return {"replies": replies, "syncs": cogs[0].db.guildsyncs.docs, "settings": cogs[0].bot.data.guilds.writes,
            "prompts": cogs[0].db.guildsync_prompts.docs, "requests": [url for url, _ in requests]}


async def answer_guildsync_prompt(server, answer, *, users, responses=(), prompts=(), syncs=()):
    """The prompted leader (user 2) presses Confirm or Deny on prompt
    message 555. Returns {"reply", "requester": DMs to the requester (user
    1), "syncs", "prompts", "deleted": whether the prompt message was
    deleted}."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.guildsync import GuildSyncPromptUserConfirmView

    cog, session = _guildsync_cog(server, users, responses, syncs, prompts=prompts)
    requester = MagicMock(id=1, discriminator="0")
    requester.name = "admin"
    requester.send = AsyncMock()
    cog.bot.get_user = {1: requester}.get
    view = GuildSyncPromptUserConfirmView(cog)
    interaction = MagicMock()
    interaction.user.id = 2
    interaction.message.id = 555
    interaction.message.delete = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    button = next(item for item in view.children if item.custom_id == f"guildsync:{'confirm' if answer else 'deny'}")
    await button.callback(interaction)
    if interaction.response.edit_message.await_count:
        reply = interaction.response.edit_message.await_args.kwargs["content"]
    else:
        reply = interaction.followup.send.await_args.kwargs["content"]
    return {"reply": reply, "requester": [c.args[0] for c in requester.send.await_args_list],
            "syncs": cog.db.guildsyncs.docs, "prompts": cog.db.guildsync_prompts.docs,
            "deleted": interaction.message.delete.await_count == 1}


async def server_command(command, server, *, users=None, settings=None, responses=(), **options):
    """Run a /server command (force_account_names, sync_now or
    default_guild) on `server`. Returns (replies, settings writes, other
    work started: ["rename", "guildsync"])."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.server import Server

    handler = {"force_account_names": Server.server_force_account_names,
               "sync_now": Server.sync_now, "default_guild": Server.guild_default}[command]
    started = []
    guilds = MemorySettings({server.id: settings or {}})
    holder = []

    def cog_for(session, _):
        cog = Server(fake_bot(session, MemorySettings(users or {})))
        cog.bot.data.guilds = guilds

        async def rename(guild):
            started.append("rename")

        async def guildsync(ctx):
            started.append("guildsync")

        cog.force_guild_account_names = rename
        cog.bot.get_cog = {"GuildSync": SimpleNamespace(guildsync_now=guildsync)}.get
        return cog

    def in_server(interaction):
        interaction.guild = server
        holder.append(interaction)

    await run_command(cog_for, handler, list(responses) or [(500, {})], permissions=(),
                      on_interaction=in_server, **options)
    interaction = holder[0]
    replies = [call.args[0] if call.args else call.kwargs.get("content")
               for mock in (interaction.response.send_message, interaction.followup.send)
               for call in mock.await_args_list]
    return replies, guilds.writes, started


async def run_forced_account_names(server, users):
    """One run of the 5-minute forced account names loop. Returns
    {member id: new nickname} for members renamed."""
    from unittest.mock import AsyncMock

    from gw2bot.cogs.server import Server

    cog = Server(fake_bot(None, MemorySettings(users)))
    cog.bot.data.guilds = MemorySettings({server.id: {"force_account_names": True}})
    cog.bot.get_guild = {server.id: server}.get
    renamed = {}
    for member in server.members:
        async def edit(nick=None, reason=None, member=member):
            renamed[member.id] = nick

        member.edit = edit
    await type(cog).forced_account_names.coro(cog)
    return renamed



# --- Rebuilt on the shared fakes ----------------------------------------------------

def discord_member(member_id, *, roles=1, days_on_server=3):
    """A server member to be, for run_guildsync: `roles` roles (1 is just
    @everyone)."""
    return SimpleNamespace(id=member_id, extra_roles=roles - 1, days=days_on_server)


async def run_guildsync(members, accounts, responses, *, syncs=1, purge=True):
    """Run a full guild sync on a server with `members` (see
    discord_member), whose accounts are {member id: account name}, against
    `syncs` guild syncs with tag and rank roles off. `responses` are each
    sync's guild/:id/members (see FakeSession). Returns the ids of the
    members kicked."""
    from gw2bot.cogs.guildsync import GuildSync

    server = FakeServer()
    for spec in members:
        roles = [server.role(f"Role {spec.id}.{i}") for i in range(spec.extra_roles)]
        server.member(spec.id, *roles, days_on_server=spec.days)
    users = MemorySettings({member_id: stored_key(["account", "guilds"], account_name=name)
                            for member_id, name in accounts.items()})
    cog = GuildSync(fake_bot(FakeSession(*responses), users))
    docs = [{"_id": f"sync{i}", "guild_id": 10, "gid": f"GUILD-{i}", "key": "LEADER", "rank_roles": {},
             "tag_role": None, "enabled": {"ranks": False, "tag": False}, "name": f"Guild {i}", "tag": "EX"}
            for i in range(syncs)]
    cog.db = gw2_db(guildsyncs=docs)
    cog.bot.data.guilds = MemorySettings({10: {"guildsync": {"enabled": True, "purge": purge}}})
    await cog.run_guildsyncs(server)
    return server.kicked


async def run_daily_notifier(settings, *, previous_message_exists=True, channel_exists=True, can_send=True,
                             can_embed=True):
    """One 23:40 daily notifier run for a server whose `daily` settings
    are `settings` (channel 5; the previous post is message 999). Returns
    {"sent", "edited", "deleted", "pinned", "unpinned": [message ids],
    "texts": [text-only messages], "embeds": [embeds sent, as dicts],
    "writes": server settings writes}."""
    from unittest.mock import AsyncMock

    channel = RecordingChannel(5, 10, existing=[999] if previous_message_exists else [], can_send=can_send,
                               can_embed=can_embed)
    cog = _daily()
    cog.cache_dailies = AsyncMock()
    cog.bot.data.config.get = AsyncMock(return_value={"cache": {"dailies_tomorrow": {"raids": [], "fractals": []}}})
    cog.bot.data.guilds = MemorySettings({10: {"daily": {"on": True, "channel": 5, "categories": ["psna"],
                                                         "message": 999, **settings}}})
    cog.bot.get_channel = {5: channel}.get if channel_exists else {}.get
    await type(cog).send_daily_notifs.coro(cog)
    for _ in range(50):
        await asyncio.sleep(0)
    return {
        "sent": [1001 + i for i, (_, embed, _) in enumerate(channel.sent) if embed],
        "texts": [content for content, embed, _ in channel.sent if embed is None],
        "embeds": [embed for _, embed, _ in channel.sent if embed],
        "edited": channel.edited, "deleted": channel.deleted, "pinned": channel.pinned, "unpinned": channel.unpinned,
        "writes": cog.bot.data.guilds.writes,
    }


# The API key role on the servers below
KEY_ROLE = FakeRole(None, 77, "API key", 10)


def server_member(member_id, *roles):
    """A member with `roles`, not yet on a server; role changes are
    recorded in member.changes."""
    return FakeMember(None, member_id, roles)


def _key_server(members, *, role_exists=True, can_manage_roles=True):
    server = FakeServer(can_manage_roles=can_manage_roles)
    for member in members:
        server.add(member)
    if role_exists:
        server.roles[KEY_ROLE.id] = KEY_ROLE
    else:
        server.roles.pop(KEY_ROLE.id, None)
    return server


async def run_key_role_sync(members, users, *, settings=None, role_exists=True, can_manage_roles=True):
    """One run of the 5-minute API key role sync on server 10, whose
    `key_sync` settings are `settings` (default: on, role 77). `users` are
    settings by member id. Returns {member id: role changes}."""
    from gw2bot.cogs.keys import Keys

    server = _key_server(members, role_exists=role_exists, can_manage_roles=can_manage_roles)
    cog = Keys(fake_bot(None, MemorySettings(users)))
    cog.bot.data.guilds = MemorySettings({10: {"key_sync": settings or {"enabled": True, "role": 77}}})
    cog.bot.get_guild = {10: server}.get
    await type(cog).key_sync_task.coro(cog)
    return {m.id: m.changes for m in members}


async def member_joins(member, users, *, settings=None):
    """A member joins server 10 (API key role 77 per `settings`). Returns
    their role changes."""
    from gw2bot.cogs.keys import Keys

    _key_server([member])
    cog = Keys(fake_bot(None, MemorySettings(users)))
    cog.bot.data.guilds = MemorySettings({10: {"key_sync": settings or {"enabled": True, "role": 77}}})
    await type(cog).on_member_join(cog, member)
    return member.changes
