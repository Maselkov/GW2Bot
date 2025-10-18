import datetime
import json
import logging
from types import SimpleNamespace

import discord
from discord.ext import commands
from PIL import ImageFont
import httpx

from .account import AccountMixin
from .achievements import AchievementsMixin
from .api import ApiMixin

# from .characters import CharactersMixin
from .commerce import CommerceMixin
from .daily import DailyMixin
from .database import DatabaseMixin
from .emojis import EmojiMixin
from .events import EventsMixin, EventTimerReminderUnsubscribeView
from .evtc import EvtcMixin
from .exceptions import APIError, APIInactiveError, APIInvalidKey, APIKeyError
from .guild import GuildMixin
from .guild.sync import GuildSyncPromptUserConfirmView
from .guildmanage import GuildManageMixin
from .key import KeyMixin
from .misc import MiscMixin
from .notifiers import NotiifiersMixin
from .pvp import PvpMixin
from .skills import SkillsMixin
from .wallet import WalletMixin
from .worldsync import WorldsyncMixin
from .wvw import WvwMixin
from .core.container import ServiceContainer
from .adapters.discord.commands import register_all as register_commands


class GuildWars2(
    commands.Cog,
    AccountMixin,
    AchievementsMixin,
    ApiMixin,
    # CharactersMixin,
    CommerceMixin,
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
    PvpMixin,
    SkillsMixin,
    WalletMixin,
    WorldsyncMixin,
    WvwMixin,
):
    """Guild Wars 2 commands"""

    # Hint editors that this attribute exists and its type
    container: ServiceContainer

    def __init__(self, bot):
        self.bot = bot
        self.container = ServiceContainer(bot)
        self.db = self.bot.database.db.gw2
        with open("cogs/guildwars2/gamedata.json", encoding="utf-8", mode="r") as f:
            self.gamedata = json.load(f)
        with open(
            "cogs/guildwars2/instabilities.json", encoding="utf-8", mode="r"
        ) as f:
            self.instabilities = json.load(f)
        self.session = bot.session
        self.httpx_client = httpx.AsyncClient()
        self.boss_schedule = self.generate_schedule()
        self.embed_color = 0xC12D2B
        self.log = logging.getLogger(__name__)
        self.tasks = []
        self.waiting_for = []
        self.emojis = {}
        self.chatcode_preview_opted_out_guilds = set()
        try:
            self.font = ImageFont.truetype("GWTwoFont1p1.ttf", size=30)
        except IOError:
            self.font = ImageFont.load_default()
        setup_tasks = [self.prepare_emojis, self.prepare_linkpreview_guild_cache]
        for task in setup_tasks:
            bot.loop.create_task(task())
        self.tasks = [
            self.game_update_checker,
            self.news_checker,
            self.gem_tracker,
            self.world_population_checker,
            self.guild_synchronizer,
            self.boss_notifier,
            self.forced_account_names,
            self.event_reminder_task,
            self.worldsync_task,
            self.post_evtc_notifications,
            self.daily_mystic_forger_checker_task,
            self.key_sync_task,
            self.cache_dailies_tomorrow,
            self.swap_daily_tomorrow_and_today,
            self.send_daily_notifs,
        ]
        for task in self.tasks:
            task.start()

    async def cog_load(self):
        self.bot.add_view(EventTimerReminderUnsubscribeView(self))
        self.bot.add_view(GuildSyncPromptUserConfirmView(self))
        # Auto-discover and register commands in adapters/discord/commands
        register_commands(self)
        # Sync command tree so newly registered slash commands are available
        # Fast-path: copy global commands to each guild for immediate availability
        for guild in getattr(self.bot, "guilds", []) or []:
            try:
                self.bot.tree.copy_global_to(guild=guild)
                await self.bot.tree.sync(guild=guild)
            except Exception:
                continue

    async def cog_unload(self):
        for task in self.tasks:
            task.cancel()
        await self.httpx_client.aclose()

    async def cog_error_handler(self, interaction, error):
        msg = ""
        user = interaction.user
        if isinstance(error, APIKeyError):
            msg = str(error)
        elif isinstance(error, APIInactiveError):
            msg = "The API is currently down. " "Try again later.".format
        elif isinstance(error, APIInvalidKey):
            msg = "Your API key is invalid! Remove your " "key and add a new one"
        elif isinstance(error, APIError):
            msg = f"API has responded with the following error: " f"`{error}`".format(
                user, error
            )
        return msg

    def can_embed_links(self, ctx):
        if not isinstance(ctx.channel, discord.abc.GuildChannel):
            return True
        return ctx.channel.permissions_for(ctx.me).embed_links

    async def get_embed_color(self, ctx):
        if not hasattr(ctx, "author"):
            return self.embed_color
        doc = await self.bot.database.users.find_one(
            {"_id": ctx.author.id}, {"embed_color": 1, "_id": 0}
        )
        if doc and doc["embed_color"]:
            return int(doc["embed_color"], 16)
        return self.embed_color

    def tell_off(
        self, component_context, message="Only the command owner may do that."
    ):
        self.bot.loop.create_task(component_context.send(message, ephemeral=True))

    # Command methods are auto-registered via adapters; keep Cog thin

    # Backward-compatible shims for migrated helpers
    def get_crafting(self, character):
        """Shim: delegate to CharactersService.get_crafting."""
        try:
            return self.container.characters_service.get_crafting(character)
        except Exception:
            # Fallback to simple formatting to avoid breaking
            out = []
            for c in character.get("crafting", []) or []:
                r = c.get("rating")
                d = c.get("discipline")
                if r is not None and d:
                    out.append(f"Level {r} {d}")
            return out

    async def get_profession(self, profession, specializations):
        """Shim: delegate to CharactersService.get_profession.

        specializations is a list of specialization documents (from DB).
        """
        data = await self.container.characters_service.get_profession(
            profession, specializations, self.gamedata
        )
        # Preserve attribute access and Color instance expected by legacy code
        if isinstance(data.get("color"), int):
            color = discord.Color(data["color"])  # type: ignore[index]
        else:
            color = data.get("color")
        return SimpleNamespace(
            name=data.get("name"), icon=data.get("icon"), color=color
        )


async def setup(bot):
    cog = GuildWars2(bot)
    await bot.database.setup_cog(
        cog,
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
