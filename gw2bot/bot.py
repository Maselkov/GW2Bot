"""The bot itself, ported from Toothy (toothy/toothy.py at 329c6eb)."""
import datetime
import hashlib
import json
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from .db.legacy import MongoController
from .gw2api import Client

log = logging.getLogger(__name__)

EXTENSIONS = ["gw2bot.owner", "gw2bot.cogs.guildwars2"]


def intents():
    intents = discord.Intents.default()
    # Guild sync and worldsync react to members joining and edit their roles
    intents.members = True
    # Chat code previews and EVTC uploads read message content
    intents.message_content = True
    return intents


def command_tree_hash(tree):
    """Hash of the global command payload that tree.sync() would send."""
    payload = sorted(
        (command.to_dict(tree) for command in tree.get_commands()),
        key=lambda c: (c.get("type", 1), c["name"]),
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def readable_permissions(permissions):
    return ", ".join(
        p.replace("guild", "server").replace("_", " ").title() for p in permissions
    )


class GW2Bot(commands.AutoShardedBot):

    def __init__(self, settings):
        super().__init__(
            command_prefix=commands.when_mentioned_or(*settings.prefixes),
            description="https://github.com/Maselkov/GW2Bot",
            owner_id=settings.owner_id,
            case_insensitive=True,
            intents=intents(),
        )
        self.settings = settings
        self.database = MongoController(self, settings.mongo_uri, settings.mongo_db)
        self.state = self.database.db.gw2bot_state
        self.available = True
        self.session = None
        self.gw2api = None
        self.test_guild = settings.test_guild
        self.uptime = datetime.datetime.now(datetime.timezone.utc)
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self.gw2api = Client(self.session)
        for extension in EXTENSIONS:
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
        digest = command_tree_hash(self.tree)
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
                    "hash": digest or command_tree_hash(self.tree),
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
        await self.database.client.close()

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        msg = ""
        if isinstance(error, app_commands.CommandInvokeError):
            cog = getattr(interaction.command, "binding", None)
            if hasattr(cog, "cog_error_handler"):
                msg = await cog.cog_error_handler(interaction, error.original)
            if not msg:
                log.exception("Exception in command", exc_info=error.original)
                msg = (
                    "Something went wrong. If this problem persists, please "
                    "report it or ask about it in the support server."
                )
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "This command cannot be used in DMs"
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = "You cannot use this command again for the next {:.2f} seconds".format(
                error.retry_after
            )
        elif isinstance(error, app_commands.MissingPermissions):
            msg = "You're missing the following permissions to use this command: `{}`".format(
                readable_permissions(error.missing_permissions)
            )
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = (
                "The bot is missing the following permissions to be able to "
                "run this command:\n`{}`\nPlease add them then try again".format(
                    readable_permissions(error.missing_permissions)
                )
            )
        elif isinstance(error, app_commands.CommandNotFound):
            msg = (
                "The command you used could not be found. The bot owner "
                "probably forgot to sync commands. Try again later."
            )
        if not msg:
            return
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
