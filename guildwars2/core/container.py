import logging

from .api_client import GW2ApiClient
from .services.account import AccountService
from .services.achievements import AchievementsService
from .services.characters import CharactersService
from .services.keys import KeyService
from .services.inventory import InventoryService
from ..data.repositories import Gw2Repository


class ServiceContainer:
    """Constructs and caches service singletons.

    Pass in the bot to reuse its event loop, session, and database handles.
    """

    def __init__(self, bot):
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.api = GW2ApiClient(session=bot.session, logger=self.log)
        self.repo = Gw2Repository(bot.database.db.gw2)
        self.utils = {}
        self._account_service = None
        self._achievements_service = None
        self._characters_service = None
        self._keys_service = None
        self._inventory_service = None

    @property
    def account_service(self) -> AccountService:
        if not self._account_service:
            self._account_service = AccountService(self.api, self.repo, self.utils)
        return self._account_service

    @property
    def achievements_service(self) -> AchievementsService:
        if not self._achievements_service:
            self._achievements_service = AchievementsService(self.api, self.repo)
        return self._achievements_service

    @property
    def characters_service(self) -> CharactersService:
        if not self._characters_service:
            self._characters_service = CharactersService(self.api, self.repo)
        return self._characters_service

    @property
    def keys_service(self) -> KeyService:
        if not self._keys_service:
            # Pass the top-level database handle for compatibility
            self._keys_service = KeyService(self.bot.database)
        return self._keys_service

    @property
    def inventory_service(self) -> InventoryService:
        if not self._inventory_service:
            self._inventory_service = InventoryService(self.api)
        return self._inventory_service
