import datetime
import json
import logging
import aiohttp
from .account import AccountMixin
from .achievements import AchievementsMixin
from .api import ApiMixin
from .characters import CharactersMixin
from .commerce import CommerceMixin
from .daily import DailyMixin
from .database import DatabaseMixin
from .events import EventsMixin
from .guild import GuildMixin
from .guildmanage import GuildManageMixin
from .key import KeyMixin
from .misc import MiscMixin
from .notifiers import NotiifiersMixin
from .pvp import PvpMixin
from .wallet import WalletMixin
from .wvw import WvwMixin
from .exceptions import APIKeyError, APIError, APIInvalidKey, APIInactiveError


class GuildWars2(AccountMixin, AchievementsMixin, ApiMixin, CharactersMixin,
                 CommerceMixin, DailyMixin, DatabaseMixin, EventsMixin,
                 GuildMixin, GuildManageMixin, KeyMixin, MiscMixin,
                 NotiifiersMixin, PvpMixin, WalletMixin, WvwMixin):
    """Guild Wars 2 commands"""

    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.database.db.gw2
        with open(
                "cogs/guildwars2/gamedata.json", encoding="utf-8",
                mode="r") as f:
            self.gamedata = json.load(f)
        self.session = aiohttp.ClientSession(loop=self.bot.loop)
        self.boss_schedule = self.generate_schedule()
        self.embed_color = 0xc12d2b
        self.log = logging.getLogger(__name__)
        self.tasks = []
        self.waiting_for = []

    def __unload(self):
        for task in self.tasks:
            task.cancel()
        self.tasks = []
        self.session.close()

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


def setup(bot):
    cog = GuildWars2(bot)
    loop = bot.loop
    loop.create_task(
        bot.database.setup_cog(cog, {
            "cache": {
                "day": datetime.datetime.utcnow().weekday(),
                "news": [],
                "build": 0,
                "dailies": {}
            }
        }))
    tasks = (cog.game_update_checker, cog.daily_checker, cog.news_checker,
             cog.gem_tracker, cog.world_population_checker,
             cog.guild_synchronizer, cog.boss_notifier,
             cog.forced_account_names)
    for task in tasks:
        cog.tasks.append(loop.create_task(task()))
    bot.add_cog(cog)
