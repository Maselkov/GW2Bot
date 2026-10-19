"""What every GW2Bot cog shares."""
from discord.ext import commands

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

    async def get_embed_color(self, ctx):
        # Toothy's per-user embed_color only ever applied to text commands
        # (contexts with .author), never to slash commands
        return self.embed_color
