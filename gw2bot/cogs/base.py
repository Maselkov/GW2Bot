"""What every GW2Bot cog shares."""
from discord.ext import commands

EMBED_COLOR = 0xC12D2B


class GW2Cog(commands.Cog):
    """Base for GW2Bot's cogs: the API client, data, users' keys, game data
    and emojis, set up by the bot."""

    embed_color = EMBED_COLOR

    def __init__(self, bot):
        self.bot = bot

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

    async def get_embed_color(self, ctx):
        # Toothy's per-user embed_color only ever applied to text commands
        # (contexts with .author), never to slash commands
        return self.embed_color
