"""What every GW2Bot cog shares."""
from collections import defaultdict

from discord.ext import commands

from ..gw2api.errors import APIError

EMBED_COLOR = 0xC12D2B


class GW2Cog(commands.Cog):
    """Base for GW2Bot's cogs: the API client, data, users' keys, game data
    and emojis, set up by the bot."""

    embed_color = EMBED_COLOR

    def __init__(self, bot):
        self.bot = bot
        # Game data caches, guild syncs, EVTC, ... (items, skins, ...)
        self.db = bot.data.gw2

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
    ):
        """GET an endpoint with `key`, or else `user`'s key (checking `scopes`)."""
        if key is None and user:
            key = (await self.fetch_key(user, scopes))["key"]
        data = await self.api.get(endpoint, key=key, schema=schema_version or schema_string)
        if endpoint == "account" and user:
            self.keys.check_account_rename_later(user, key, data)
        return data

    async def call_multiple(
        self, endpoints, user=None, scopes=None, key=None, schema_version=None, schema_string=None
    ):
        """GET several endpoints with one key; results are in input order."""
        if key is None and user:
            key = (await self.fetch_key(user, scopes))["key"]
        return await self.api.get_many(endpoints, key=key, schema=schema_version or schema_string)

    def get_emoji(self, ctx, emoji, **kwargs):
        """See gw2bot.emojis.Emojis.get."""
        return self.bot.gw2_emojis.get(ctx, emoji, **kwargs)

    @property
    def emojis(self):
        """Registered emoji ids by name."""
        return self.bot.gw2_emojis.ids

    def gold_to_coins(self, ctx, money):
        """Copper as gold/silver/copper, with their emojis where usable."""
        gold, remainder = divmod(money, 10000)
        silver, copper = divmod(remainder, 100)
        kwargs = {"fallback": True, "fallback_fmt": " {} "}
        gold = "{}{}".format(gold, self.get_emoji(ctx, "gold", **
                                                  kwargs)) if gold else ""
        silver = "{}{}".format(silver, self.get_emoji(
            ctx, "silver", **kwargs)) if silver else ""
        copper = "{}{}".format(copper, self.get_emoji(
            ctx, "copper", **kwargs)) if copper else ""
        return "".join(filter(None, [gold, silver, copper]))

    async def fetch_item(self, item):
        """The cached item document."""
        return await self.db.items.find_one({"_id": item})

    async def get_title(self, title_id):
        """A title's name, or "" if it isn't cached."""
        try:
            results = await self.db.titles.find_one({"_id": title_id})
            title = results["name"]
        except (KeyError, TypeError):
            return ""
        return title

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
            space_name = name
            for s in space:
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
                flattened = defaultdict(lambda: [])
            else:
                flattened = defaultdict(int)
            for count_dict in counts.values():
                for k, v in count_dict.items():
                    flattened[k] += v
            return flattened
        return counts

    async def get_embed_color(self, ctx):
        # Toothy's per-user embed_color only ever applied to text commands
        # (contexts with .author), never to slash commands
        return self.embed_color
