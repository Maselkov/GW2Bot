"""The bot itself, ported from Toothy (toothy/toothy.py at 329c6eb)."""
import asyncio
import datetime
import hashlib
import json
import logging
import pkgutil

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from .db import Data
from .db.migrate import migrate
from .emojis import Emojis
from .errors import error_message
from .gamedata import load_gamedata
from .gw2api import Client
from .i18n import N_, Catalog, GW2Translator, interaction_language
from .keys import ApiKeys

log = logging.getLogger(__name__)

# Caches and settings in the config document the cogs expect
CONFIG_DEFAULTS = {
    "cache": {"news": [], "build": 0, "dailies": {}, "dailies_tomorrow": {}},
    "emojis": {},
}

# Modules in gw2bot/cogs that aren't extensions
NOT_EXTENSIONS = {"base"}


def extensions():
    """The owner commands, then every cog in gw2bot/cogs (one module or
    package per feature, each with a setup(bot))."""
    from . import cogs

    names = sorted(m.name for m in pkgutil.iter_modules(cogs.__path__) if m.name not in NOT_EXTENSIONS)
    return ["gw2bot.owner"] + [f"gw2bot.cogs.{name}" for name in names]


def intents():
    intents = discord.Intents.default()
    # Guild sync reacts to members joining and edit their roles
    intents.members = True
    # Chat code previews and EVTC uploads read message content
    intents.message_content = True
    return intents


async def command_tree_hash(tree):
    """Hash of the global command payload that tree.sync() would send,
    translations included."""
    translator = tree.translator
    if translator:
        payload = [await command.get_translated_payload(tree, translator) for command in tree.get_commands()]
    else:
        payload = [command.to_dict(tree) for command in tree.get_commands()]
    payload.sort(key=lambda c: (c.get("type", 1), c["name"]))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# The permissions commands check, as Discord names them
PERMISSION_NAMES = {
    "embed_links": N_("Embed Links"),
    "kick_members": N_("Kick Members"),
    "manage_channels": N_("Manage Channels"),
    "manage_guild": N_("Manage Server"),
    "manage_nicknames": N_("Manage Nicknames"),
    "manage_roles": N_("Manage Roles"),
    "use_external_emojis": N_("Use External Emoji"),
}


def readable_permissions(permissions, translate=lambda text: text):
    return ", ".join(
        translate(PERMISSION_NAMES[p]) if p in PERMISSION_NAMES
        else p.replace("guild", "server").replace("_", " ").title()
        for p in permissions
    )


class GW2Bot(commands.AutoShardedBot):

    def __init__(self, settings):
        super().__init__(
            command_prefix=commands.when_mentioned_or(*settings.prefixes),
            description="https://github.com/Maselkov/GW2Bot",
            owner_id=settings.owner_id,
            case_insensitive=True,
            intents=intents(),
            # Chunking every server takes many minutes of gateway rate
            # limits; what needs a server's members chunks it first
            chunk_guilds_at_startup=False,
        )
        self.settings = settings
        self.data = Data(settings.mongo_uri, settings.mongo_db)
        self.state = self.data.state
        self.gamedata, self.instabilities = load_gamedata()
        self.catalog = Catalog.load()
        self.keys = ApiKeys(self.data.users, self.catalog)
        # Not self.emojis: discord.py's Client.emojis is the emoji cache
        self.gw2_emojis = Emojis(self, self.data.config)
        self.available = True
        self.session = None
        self.gw2api = None
        self.test_guild = settings.test_guild
        # Users fetched because they weren't cached, by id
        self.fetched_users = {}
        self.uptime = datetime.datetime.now(datetime.timezone.utc)
        self.tree.on_error = self.on_app_command_error

    async def get_or_fetch_user(self, user_id):
        """A user from the cache, or else fetched from Discord once and
        remembered. None if there's no such user."""
        user = self.get_user(user_id) or self.fetched_users.get(user_id)
        if user:
            return user
        try:
            user = await self.fetch_user(user_id)
        except discord.NotFound:
            return None
        self.fetched_users[user_id] = user
        return user

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self.gw2api = Client(self.session)
        # Before any cog touches the data; a failure stops startup rather
        # than running on a half-copied database
        report = await migrate(self.data.client, self.settings.migrate_from_db, self.settings.mongo_db)
        log.info(report.summary())
        await self.data.ensure_indexes()
        await self.data.config.ensure_defaults(CONFIG_DEFAULTS)
        await self.gw2_emojis.load()
        await self.tree.set_translator(GW2Translator(self.catalog))
        for extension in extensions():
            await self.load_extension(extension)
        if self.settings.auto_sync:
            try:
                await self.sync_commands_if_changed()
            except Exception:
                log.exception("Syncing commands failed; run >sync once the cause is fixed")

    async def sync_commands_if_changed(self):
        """Sync global commands if they changed since the last recorded sync.

        Returns whether a sync happened.
        """
        digest = await command_tree_hash(self.tree)
        doc = await self.state.find_one({"_id": "command_tree"})
        if doc and doc.get("hash") == digest:
            log.info("Commands unchanged since the last sync")
            return False
        await self.tree.sync()
        await self.record_command_sync(digest)
        log.info("Synced commands")
        return True

    async def record_command_sync(self, digest=None):
        await self.state.update_one(
            {"_id": "command_tree"},
            {
                "$set": {
                    "hash": digest or await command_tree_hash(self.tree),
                    "synced_at": datetime.datetime.now(datetime.timezone.utc),
                }
            },
            upsert=True,
        )

    async def on_ready(self):
        log.info("Ready, serving %d guilds", len(self.guilds))

    async def on_message(self, message):
        # Text commands are owner-only; everything else is slash commands
        if message.author.bot or message.author.id != self.owner_id:
            return
        await self.process_commands(message)

    async def close(self):
        await super().close()
        if self.session:
            await self.session.close()
        await self.data.close()

    async def interaction_language(self, interaction):
        """See GW2Cog.lang; English if the settings can't be read quickly
        (an error is still answered before the interaction expires)."""
        try:
            return await asyncio.wait_for(interaction_language(self.data.users, interaction), 2)
        except Exception:
            log.exception("Couldn't read the user's language")
            return "en"

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        lang = await self.interaction_language(interaction)

        def t(text, **fields):
            return self.catalog.t(lang, text, **fields)

        msg = ""
        if isinstance(error, app_commands.CommandInvokeError):
            msg = error_message(error.original, lang, self.catalog)
            cog = getattr(interaction.command, "binding", None)
            if not msg and hasattr(cog, "cog_error_handler"):
                msg = await cog.cog_error_handler(interaction, error.original)
            if not msg:
                log.exception("Exception in command", exc_info=error.original)
                msg = t(N_(
                    "Something went wrong. If this problem persists, please "
                    "report it or ask about it in the support server."
                ))
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = t(N_("This command cannot be used in DMs"))
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = t(N_("You cannot use this command again for the next {seconds} seconds"),
                    seconds=f"{error.retry_after:.2f}")
        elif isinstance(error, app_commands.MissingPermissions):
            msg = t(N_("You're missing the following permissions to use this command: `{permissions}`"),
                    permissions=readable_permissions(error.missing_permissions, t))
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = t(N_(
                "The bot is missing the following permissions to be able to "
                "run this command:\n`{permissions}`\nPlease add them then try again"
            ), permissions=readable_permissions(error.missing_permissions, t))
        elif isinstance(error, app_commands.CommandNotFound):
            msg = t(N_(
                "The command you used could not be found. The bot owner "
                "probably forgot to sync commands. Try again later."
            ))
        if not msg:
            return
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
