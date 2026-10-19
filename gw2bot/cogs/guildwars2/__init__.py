import datetime
import logging

import discord
from PIL import ImageFont

from ...errors import error_message
from ..base import GW2Cog
from .characters import CharactersMixin
from .chatlinks import ChatLinksMixin
from .daily import DailyMixin
from .database import DatabaseMixin
from .emojis import EmojiMixin
from .events import EventsMixin, EventTimerReminderUnsubscribeView
from .evtc import EvtcMixin
from .guild import GuildMixin
from .guild.sync import GuildSyncPromptUserConfirmView
from .guildmanage import GuildManageMixin
from .key import KeyMixin
from .misc import MiscMixin
from .notifiers import NotiifiersMixin

class GuildWars2(
    GW2Cog,
    CharactersMixin,
    ChatLinksMixin,
    DailyMixin,
    DatabaseMixin,
    EmojiMixin,
    EventsMixin,
    EvtcMixin,
    GuildMixin,
    GuildManageMixin,
    KeyMixin,
    MiscMixin,
    NotiifiersMixin,
):
    """Guild Wars 2 commands"""

    def __init__(self, bot):
        super().__init__(bot)
        self.session = bot.session
        self.boss_schedule = self.generate_schedule()
        self.log = logging.getLogger(__name__)
        self.tasks = []
        self.waiting_for = []
        self.chatcode_preview_opted_out_guilds = set()
        try:
            self.font = ImageFont.truetype("GWTwoFont1p1.ttf", size=30)
        except IOError:
            self.font = ImageFont.load_default()
        self.tasks = [
            self.game_update_checker,
            self.news_checker,
            self.gem_tracker,
            self.guild_synchronizer,
            self.boss_notifier,
            self.forced_account_names,
            self.event_reminder_task,
            self.post_evtc_notifications,
            self.key_sync_task,
            self.refresh_dailies,
            self.send_daily_notifs,
        ]
        for task in self.tasks:
            task.start()

    async def cog_load(self):
        await self.prepare_linkpreview_guild_cache()
        self.bot.add_view(EventTimerReminderUnsubscribeView(self))
        self.bot.add_view(GuildSyncPromptUserConfirmView(self))

    async def cog_unload(self):
        for task in self.tasks:
            task.cancel()

    async def cog_error_handler(self, interaction, error):
        return error_message(error)

    def can_embed_links(self, ctx):
        if not isinstance(ctx.channel, discord.abc.GuildChannel):
            return True
        return ctx.channel.permissions_for(ctx.me).embed_links

    def tell_off(
        self, component_context, message="Only the command owner may do that."
    ):
        self.bot.loop.create_task(component_context.send(message, ephemeral=True))


async def setup(bot):
    cog = GuildWars2(bot)
    await bot.data.config.ensure_defaults(
        {
            "cache": {
                "day": datetime.datetime.utcnow().weekday(),
                "news": [],
                "build": 0,
                "dailies": {},
                "dailies_tomorrow": {},
            },
            "emojis": {},
        },
    )
    await bot.add_cog(cog)
