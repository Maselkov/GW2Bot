import datetime
import json
import logging

import discord
from PIL import ImageFont

from .account import AccountMixin
from .achievements import AchievementsMixin
from .api import ApiMixin
from .bt import BtMixin
from .characters import CharactersMixin
from .commerce import CommerceMixin
from .daily import DailyMixin
from .database import DatabaseMixin
from .emojis import EmojiMixin
from .events import EventsMixin
from .evtc import EvtcMixin
from .exceptions import APIError, APIInactiveError, APIInvalidKey, APIKeyError
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
                 ApiMixin, BtMixin, CharactersMixin, CommerceMixin, DailyMixin,
                 DatabaseMixin, EmojiMixin, EventsMixin, EvtcMixin, GuildMixin,
                 GuildManageMixin, KeyMixin, MiscMixin, NotiifiersMixin,
                 PvpMixin, SkillsMixin, WalletMixin, WorldsyncMixin, WvwMixin):
    """Guild Wars 2 commands"""

    def __init__(self, bot):

        self.bot = bot
        self.db = self.bot.database.db.gw2
        with open(
                "cogs/guildwars2/gamedata.json", encoding="utf-8",
                mode="r") as f:
            self.gamedata = json.load(f)
        self.session = bot.session
        self.boss_schedule = self.generate_schedule()
        self.embed_color = 0xc12d2b
        self.log = logging.getLogger(__name__)
        self.tasks = []
        self.waiting_for = []
        self.emojis = {}
        try:
            self.font = ImageFont.truetype("GWTwoFont1p1.ttf", size=30)
        except IOError:
            self.font = ImageFont.load_default()
        self.tasks = [
            self.game_update_checker, self.daily_checker, self.news_checker,
            self.gem_tracker, self.world_population_checker,
            self.guild_synchronizer, self.boss_notifier,
            self.forced_account_names, self.event_reminder_task,
            self.worldsync_task
        ]
        for task in self.tasks:
            task.start()

    def cog_unload(self):
        for task in self.tasks:
            task.cancel()

    async def error_handler(self, ctx, exc):
        user = ctx.author
        if isinstance(exc, APIKeyError):
            await ctx.send(exc)
            return
        if isinstance(exc, APIInactiveError):
            await ctx.send("{.mention}, the API is currently down. "
                           "Try again later.".format(user))
            return
        if isinstance(exc, APIInvalidKey):
            await ctx.send("{.mention}, your API key is invalid! Remove your "
                           "key and add a new one".format(user))
            return
        if isinstance(exc, APIError):
            await ctx.send(
                "{.mention}, API has responded with the following error: "
                "`{}`".format(user, exc))
            return

    def can_embed_links(self, ctx):
        if not isinstance(ctx.channel, discord.abc.GuildChannel):
            return True
        return ctx.channel.permissions_for(ctx.me).embed_links

    async def get_embed_color(self, ctx):
        doc = await self.bot.database.users.find_one({
            "_id": ctx.author.id
        }, {
            "embed_color": 1,
            "_id": 0
        })
        if doc and doc["embed_color"]:
            return int(doc["embed_color"], 16)
        return self.embed_color


def setup(bot):
    cog = GuildWars2(bot)
    loop = bot.loop
    loop.create_task(
        bot.database.setup_cog(
            cog, {
                "cache": {
                    "day": datetime.datetime.utcnow().weekday(),
                    "news": [],
                    "build": 0,
                    "dailies": {}
                },
                "emojis": {}
            }))
    loop.create_task(cog.prepare_emojis())
    bot.add_cog(cog)
