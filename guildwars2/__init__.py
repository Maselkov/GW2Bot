import asyncio
import datetime
import json
import logging

import discord

from .account import AccountMixin
from .achievements import AchievementsMixin
from .api import ApiMixin
from .characters import CharactersMixin
from .commerce import CommerceMixin
from .daily import DailyMixin
from .database import DatabaseMixin
from .emojis import EmojiMixin
from .events import EventsMixin
from .exceptions import APIError, APIInactiveError, APIInvalidKey, APIKeyError
from .guild import GuildMixin
from .guildmanage import GuildManageMixin
from .key import KeyMixin
from .misc import MiscMixin
from .notifiers import NotiifiersMixin
from .pvp import PvpMixin
from .skills import SkillsMixin
from .wallet import WalletMixin
from .wvw import WvwMixin


class GuildWars2(discord.ext.commands.Cog, AccountMixin, AchievementsMixin,
                 ApiMixin, CharactersMixin, CommerceMixin, DailyMixin,
                 DatabaseMixin, EmojiMixin, EventsMixin, GuildMixin,
                 GuildManageMixin, KeyMixin, MiscMixin, NotiifiersMixin,
                 PvpMixin, SkillsMixin, WalletMixin, WvwMixin):
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

    def cog_unload(self):
        for task in self.tasks:
            task.cancel()
        self.tasks = []

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

    async def run_task(self, f, interval=60):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                await f()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.exception(e)
                continue
            await asyncio.sleep(interval)

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
    tasks = {
        cog.game_update_checker: 60,
        cog.daily_checker: 60,
        cog.news_checker: 180,
        cog.gem_tracker: 150,
        cog.world_population_checker: 300,
        cog.guild_synchronizer: 60,
        cog.boss_notifier: 300,
        cog.forced_account_names: 300
    }
    for kv in tasks.items():
        cog.tasks.append(loop.create_task(cog.run_task(*kv)))
    bot.add_cog(cog)
