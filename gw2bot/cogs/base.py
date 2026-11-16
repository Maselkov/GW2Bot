"""What every GW2Bot cog shares."""
import asyncio
import logging
from collections import defaultdict

from discord.app_commands import Choice
from discord.ext import commands

from ..gw2api.errors import APIError
from ..i18n import DEFAULT_LANGUAGE, N_, interaction_language, localized, resolve_language
from ..utils.db import prepare_search

EMBED_COLOR = 0xC12D2B
log = logging.getLogger(__name__)


class GW2Cog(commands.Cog):
    """Base for GW2Bot's cogs: the API client, data, users' keys, game data
    and emojis, set up by the bot."""

    embed_color = EMBED_COLOR

    def __init__(self, bot):
        self.bot = bot
        # Game data caches, guild syncs, EVTC, ... (items, skins, ...)
        self.db = bot.data.gw2
        # Work started with run_in_background that hasn't finished
        self.background_tasks = set()

    def run_in_background(self, coro, description):
        """Run `coro` without waiting for it. The task is kept until it's
        done (asyncio only holds weak references), and what it raises is
        logged with `description` instead of being lost."""
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)

        def finished(task):
            self.background_tasks.discard(task)
            if not task.cancelled() and task.exception():
                log.error("Error in the background: %s", description, exc_info=task.exception())

        task.add_done_callback(finished)
        return task

    async def users_by_id(self, user_ids):
        """{id: settings} for the users among `user_ids` who have any, in
        one read."""
        return {doc["_id"]: doc async for doc in self.bot.data.users.find({"_id": {"$in": list(user_ids)}})}

    @property
    def api(self):
        return self.bot.gw2api

    @property
    def data(self):
        return self.bot.data

    @property
    def keys(self):
        return self.bot.keys

    @property
    def gamedata(self):
        return self.bot.gamedata

    @property
    def instabilities(self):
        return self.bot.instabilities

    async def fetch_key(self, user, scopes=None):
        """The user's active key document; raises APIKeyError if they have
        none or it lacks `scopes`."""
        return await self.keys.get(user, scopes)

    async def call_api(
        self,
        endpoint,
        user=None,
        scopes=None,
        key=None,
        schema_version=None,
        schema_string=None,
        lang=None,
    ):
        """GET an endpoint with `key`, or else `user`'s key (checking
        `scopes`), with its text in `lang` (default English)."""
        if key is None and user:
            key = (await self.fetch_key(user, scopes))["key"]
        data = await self.api.get(endpoint, key=key, schema=schema_version or schema_string, lang=lang)
        if endpoint == "account" and user:
            self.keys.check_account_rename_later(user, key, data)
        return data

    async def call_multiple(
        self, endpoints, user=None, scopes=None, key=None, schema_version=None, schema_string=None, lang=None
    ):
        """GET several endpoints with one key; results are in input order."""
        if key is None and user:
            key = (await self.fetch_key(user, scopes))["key"]
        return await self.api.get_many(endpoints, key=key, schema=schema_version or schema_string, lang=lang)

    async def lang(self, interaction):
        """The language to answer `interaction` in: the user's /language
        setting, else their Discord client's language, else English."""
        return await interaction_language(self.bot.data.users, interaction)

    async def guild_lang(self, guild):
        """The language to post in `guild` in: its /server language setting,
        else its Discord language (community servers set one), else
        English."""
        settings = await self.bot.data.guilds.get(guild.id)
        return resolve_language(settings.get("language"), guild.preferred_locale)

    def settings_lang(self, settings, guild=None):
        """The language to post in a server in, from its settings document
        when it's already read (in loops over servers)."""
        return resolve_language(settings.get("language"), guild.preferred_locale if guild else None)

    async def user_lang(self, user_id):
        """The language for a message to a user outside an interaction (a
        DM): their /language setting, else English."""
        settings = await self.bot.data.users.get(user_id)
        return resolve_language(settings.get("language"))

    def t(self, lang, text, /, **fields):
        """`text` in `lang`; see gw2bot.i18n.Catalog.t."""
        return self.bot.catalog.t(lang, text, **fields)

    def get_emoji(self, ctx, emoji, **kwargs):
        """See gw2bot.emojis.Emojis.get."""
        return self.bot.gw2_emojis.get(ctx, emoji, **kwargs)

    @property
    def emojis(self):
        """Registered emoji ids by name."""
        return self.bot.gw2_emojis.ids

    def gold_to_coins(self, ctx, money, lang=DEFAULT_LANGUAGE):
        """Copper as gold/silver/copper, with their emojis where usable,
        else their names in `lang`."""
        gold, remainder = divmod(money, 10000)
        silver, copper = divmod(remainder, 100)
        coins = ((gold, "gold", N_("gold")), (silver, "silver", N_("silver")), (copper, "copper", N_("copper")))
        text = ""
        for amount, emoji_name, name in coins:
            if amount:
                emoji = self.get_emoji(ctx, emoji_name)
                text += f"{amount}{emoji}" if emoji else f"{amount} {self.t(lang, name)} "
        return text

    async def fetch_item(self, item):
        """The cached item document."""
        return await self.db.items.find_one({"_id": item})

    async def find_by_name(self, collection, current, lang=DEFAULT_LANGUAGE, limit=25, **filters):
        """Up to `limit` cached documents matching `filters` whose name in
        `lang` starts with `current`, then those whose English name does."""
        search = prepare_search(current)
        docs = []
        if lang != DEFAULT_LANGUAGE:
            docs = await collection.find({f"l10n.{lang}.name": search, **filters}).to_list(limit)
        if len(docs) < limit:
            found = [doc["_id"] for doc in docs]
            docs += await collection.find({"name": search, "_id": {"$nin": found}, **filters}).to_list(
                limit - len(docs))
        return docs

    async def name_choices(self, collection, current, lang=DEFAULT_LANGUAGE, **filters):
        """Autocomplete choices (value: the id) for up to 25 cached
        documents whose name starts with `current` and that match
        `filters`, named in `lang`."""
        if not current:
            return []
        docs = await self.find_by_name(collection, current, lang, **filters)
        # Discord's limit on a choice's name
        return [Choice(name=localized(doc, lang)[:100], value=str(doc["_id"])) for doc in docs]

    async def resolve_id(self, interaction, value, autocomplete):
        """The id an option names: picked from its autocomplete, or else the
        first of `autocomplete`'s choices for the typed text. None if
        nothing matches."""
        if value.isdigit():
            return int(value)
        choices = await autocomplete(interaction, value)
        return int(choices[0].value) if choices else None

    async def get_title(self, title_id, lang=DEFAULT_LANGUAGE):
        """A title's name in `lang`, or "" if it isn't cached."""
        try:
            results = await self.db.titles.find_one({"_id": title_id})
            title = localized(results, lang)
        except (KeyError, TypeError, AttributeError):
            return ""
        return title or ""

    def rarity_to_color(self, rarity):
        return int(self.gamedata["items"]["rarity_colors"][rarity], 0)

    async def find_items_in_account(self,
                                    user,
                                    item_ids,
                                    *,
                                    doc=None,
                                    flatten=False,
                                    search=False,
                                    results=None):
        """Counts of `item_ids` across the account: bank, shared inventory,
        material storage, characters' bags and equipment, and the trading
        post delivery box. {item id: {place: count}}, or with search=True,
        {item id: {place: [in inventory, equipped]}}; flatten merges the
        places."""
        if not doc:
            doc = await self.fetch_key(user, ["inventories", "characters"])
        endpoints = [
            "account/bank", "account/inventory", "account/materials",
            "characters?page=0&page_size=200"
        ]
        if not results:
            results = await self.call_multiple(
                endpoints,
                key=doc["key"],
                schema_string="2021-07-15T13:00:00.000Z")
        bank, shared, materials, characters = results
        spaces = {
            "bank": bank,
            "shared": shared,
            "material storage": materials
        }
        legendary_armory_item_ids = set()
        if search:
            counts = {
                item_id: defaultdict(lambda: [0, 0])
                for item_id in item_ids
            }
        else:
            counts = {item_id: defaultdict(int) for item_id in item_ids}

        def amounts_in_space(space, name, geared):
            for s in space:
                space_name = name
                if geared and s["location"].endswith("LegendaryArmory"):
                    if s["id"] in legendary_armory_item_ids:
                        continue
                    legendary_armory_item_ids.add(s["id"])
                    space_name = "legendary armory"
                for item_id in item_ids:
                    amt = get_amount(s, item_id)
                    if amt:
                        if search:
                            if geared:
                                # Tuple of (inventory, geared)
                                counts[item_id][space_name][1] += amt
                            else:
                                counts[item_id][space_name][0] += amt
                        else:
                            counts[item_id][space_name] += amt

        def get_amount(slot, item_id):

            def count_upgrades(slots):
                return sum(1 for i in slots if i == item_id)

            if not slot:
                return 0
            if slot["id"] == item_id:
                if "count" in slot:
                    return slot["count"]
                return 1

            if "infusions" in slot:
                infusions_sum = count_upgrades(slot["infusions"])
                if infusions_sum:
                    return infusions_sum
            if "upgrades" in slot:
                upgrades_sum = count_upgrades(slot["upgrades"])
                if upgrades_sum:
                    return upgrades_sum
            return 0

        for name, space in spaces.items():
            amounts_in_space(space, name, False)
        for character in characters:
            amounts_in_space(character["bags"], character["name"], False)
            bags = [
                bag["inventory"] for bag in filter(None, character["bags"])
            ]
            for bag in bags:
                amounts_in_space(bag, character["name"], False)
            for tab in character["equipment_tabs"]:
                amounts_in_space(tab["equipment"], character["name"], True)
        try:
            if "tradingpost" in doc["permissions"]:
                result = await self.call_api("commerce/delivery",
                                             key=doc["key"])
                delivery = result.get("items", [])
                amounts_in_space(delivery, "TP delivery", False)
        except APIError:
            pass
        if flatten:
            if search:
                flattened = defaultdict(lambda: [0, 0])
                for count_dict in counts.values():
                    for k, (inventory, geared) in count_dict.items():
                        flattened[k][0] += inventory
                        flattened[k][1] += geared
            else:
                flattened = defaultdict(int)
                for count_dict in counts.values():
                    for k, v in count_dict.items():
                        flattened[k] += v
            return flattened
        return counts

    async def guild_subdocs(self, field, query):
        """Each matching guild's `field` settings, with the guild's _id, the
        discord.Guild (or None) as _obj, and its /server language setting
        as _language."""
        async for doc in self.bot.data.guilds.find(query):
            settings = doc.get(field)
            if isinstance(settings, dict):
                yield {**settings, "_id": doc["_id"], "_obj": self.bot.get_guild(doc["_id"]),
                       "_language": doc.get("language")}

    async def get_embed_color(self, ctx):
        # Toothy's per-user embed_color only ever applied to text commands
        # (contexts with .author), never to slash commands
        return self.embed_color
