import asyncio
import datetime
import json
import logging

import discord
from PIL import ImageFont

from .account import AccountMixin
from .achievements import AchievementsMixin
from .api import ApiMixin
from .characters import CharactersMixin
from .commerce import CommerceMixin
from .daily import DailyMixin
from .database import DatabaseMixin
from discord.app_commands import AppCommandError
from discord import app_commands
from discord import Interaction
from .emojis import EmojiMixin
from .events import EventsMixin, EventTimerReminderUnsubscribeView
from .evtc import EvtcMixin
from .exceptions import APIError, APIInactiveError, APIInvalidKey, APIKeyError
from .guild.sync import GuildSyncPromptUserConfirmView
from .guild import GuildMixin
from .guildmanage import GuildManageMixin
from .key import KeyMixin
from .misc import MiscMixin
from .notifiers import NotiifiersMixin
from .pvp import PvpMixin
from .skills import SkillsMixin
from .wallet import WalletMixin
from .worldsync import WorldsyncMixin
from .wvw import WvwMixin


class GuildWars2(discord.ext.commands.Cog, AccountMixin, AchievementsMixin,
                 ApiMixin, CharactersMixin, CommerceMixin, DailyMixin,
                 DatabaseMixin, EmojiMixin, EventsMixin, EvtcMixin, GuildMixin,
                 GuildManageMixin, KeyMixin, MiscMixin, NotiifiersMixin,
                 PvpMixin, SkillsMixin, WalletMixin, WorldsyncMixin, WvwMixin):
    """Guild Wars 2 commands"""

    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.database.db.gw2
        with open("cogs/guildwars2/gamedata.json", encoding="utf-8",
                  mode="r") as f:
            self.gamedata = json.load(f)
        with open("cogs/guildwars2/instabilities.json",
                  encoding="utf-8",
                  mode="r") as f:
            self.instabilities = json.load(f)
        self.session = bot.session
        self.boss_schedule = self.generate_schedule()
        self.embed_color = 0xc12d2b
        self.log = logging.getLogger(__name__)
        self.tasks = []
        self.waiting_for = []
        self.emojis = {}
        self.chatcode_preview_opted_out_guilds = set()
        try:
            self.font = ImageFont.truetype("GWTwoFont1p1.ttf", size=30)
        except IOError:
            self.font = ImageFont.load_default()
        setup_tasks = [
            self.prepare_emojis, self.prepare_linkpreview_guild_cache
        ]
        self.guildsync_entry_number = 0
        self.guildsync_queue = asyncio.PriorityQueue()
        for task in setup_tasks:
            bot.loop.create_task(task())
        self.tasks = [
            self.game_update_checker, self.daily_checker, self.news_checker,
            self.gem_tracker, self.world_population_checker,
            self.guild_synchronizer, self.boss_notifier,
            self.forced_account_names, self.event_reminder_task,
            self.worldsync_task, self.guildsync_consumer,
            self.post_evtc_notifications,
            self.daily_mystic_forger_checker_task, self.key_sync_task
        ]
        for task in self.tasks:
            task.start()

        # TODO move this to main bot. Add code to register sub-error handlers
        @bot.tree.error
        async def on_app_command_error(interaction: Interaction,
                                       error: AppCommandError):
            responded = interaction.response.is_done()
            msg = ""
            user = interaction.user
            if isinstance(error, app_commands.NoPrivateMessage):
                msg = "This command cannot be used in DMs"
            elif isinstance(error, app_commands.CommandOnCooldown):
                msg = ("You cannot use this command again for the next "
                       "{:.2f} seconds"
                       "".format(error.retry_after))
            elif isinstance(error, app_commands.CommandInvokeError):
                exc = error.original
                if isinstance(exc, APIKeyError):
                    msg = str(exc)
                elif isinstance(exc, APIInactiveError):
                    msg = (f"{user.mention}, the API is currently down. "
                           "Try again later.".format)
                elif isinstance(exc, APIInvalidKey):
                    msg = (
                        f"{user.mention}, your API key is invalid! Remove your "
                        "key and add a new one")
                elif isinstance(exc, APIError):
                    msg = (f"{user.mention}, API has responded with the "
                           "following error: "
                           f"`{exc}`".format(user, exc))
                else:
                    self.log.exception("Exception in command, ", exc_info=exc)
                    msg = ("Something went wrong. If this problem persists, "
                           "please report it or ask about it in the "
                           "support server- https://discord.gg/VyQTrwP")
            elif isinstance(error, app_commands.MissingPermissions):
                missing = [
                    p.replace("guild", "server").replace("_", " ").title()
                    for p in error.missing_permissions
                ]
                msg = ("You're missing the following permissions to use this "
                       "command: `{}`".format(", ".join(missing)))
            elif isinstance(error, app_commands.BotMissingPermissions):
                missing = [
                    p.replace("guild", "server").replace("_", " ").title()
                    for p in error.missing_permissions
                ]
                msg = (
                    "The bot is missing the following permissions to be able to "
                    "run this command:\n`{}`\nPlease add them then try again".
                    format(", ".join(missing)))
            elif isinstance(error, app_commands.CommandNotFound):
                pass
            elif isinstance(error, app_commands.CheckFailure):
                pass
            if not responded:
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)

    async def cog_load(self):
        self.bot.add_view(EventTimerReminderUnsubscribeView(self))
        self.bot.add_view(GuildSyncPromptUserConfirmView(self))

    async def cog_unload(self):
        for task in self.tasks:
            task.cancel()

    def can_embed_links(self, ctx):
        if not isinstance(ctx.channel, discord.abc.GuildChannel):
            return True
        return ctx.channel.permissions_for(ctx.me).embed_links

    async def get_embed_color(self, ctx):
        if not hasattr(ctx, "author"):
            return self.embed_color
        doc = await self.bot.database.users.find_one({"_id": ctx.author.id}, {
            "embed_color": 1,
            "_id": 0
        })
        if doc and doc["embed_color"]:
            return int(doc["embed_color"], 16)
        return self.embed_color

    def tell_off(self,
                 component_context,
                 message="Only the command owner may do that."):
        self.bot.loop.create_task(
            component_context.send(message, ephemeral=True))


async def setup(bot):
    cog = GuildWars2(bot)
    await bot.database.setup_cog(
        cog, {
            "cache": {
                "day": datetime.datetime.utcnow().weekday(),
                "news": [],
                "build": 0,
                "dailies": {},
                "dailies_tomorrow": {}
            },
            "emojis": {}
        })
    await bot.add_cog(cog)
