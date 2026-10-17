"""MongoDB access, ported from Toothy's MongoController (toothy/database.py
at 329c6eb).

Kept method-for-method so the cog's existing data access works unchanged
against the existing document layout. To be replaced by repositories.
"""
import discord
from pymongo import AsyncMongoClient


class MongoController:

    def __init__(self, bot, uri, db_name="toothy"):
        self.bot = bot
        self.client = AsyncMongoClient(uri)
        self.db = self.client[db_name]
        self.users = self.db.users
        self.guilds = self.db.guilds
        self.channels = self.db.channels
        self.configs = self.db.configs

    async def get_prefixes(self, guild):
        if guild is None:
            return None
        doc = await self.guilds.find_one({"_id": guild.id}, {"prefixes": 1})
        if not doc:
            return None
        return doc.get("prefixes")

    async def get_user(self, user, cog=None):
        """Get user. Pass a cog instance in order to return
           cog specific settings"""
        doc = await self.users.find_one({"_id": user.id})
        if doc and cog:
            try:
                cog_doc = doc["cogs"][cog.__class__.__name__]
                cog_doc.update(_id=doc["_id"])
                return cog_doc
            except KeyError:
                return None
        return doc

    async def get_guild(self, guild, cog=None):
        """Get guild. Pass a cog instance in order to return
           cog specific settings"""
        doc = await self.guilds.find_one({"_id": guild.id})
        if doc and cog:
            try:
                cog_doc = doc["cogs"][cog.__class__.__name__]
                cog_doc.update(_id=doc["_id"])
                return cog_doc
            except KeyError:
                return None
        return doc

    async def get_channel(self, channel, cog=None):
        """Get channel. Pass a cog instance in order to return
           cog specific settings"""
        doc = await self.channels.find_one({"_id": channel.id})
        if doc and cog:
            try:
                cog_doc = doc["cogs"][cog.__class__.__name__]
                cog_doc.update(_id=doc["_id"])
                return cog_doc
            except KeyError:
                return None
        return doc

    async def get_cog_config(self, cog):
        name = cog.__class__.__name__
        return await self.configs.find_one({"cog_name": name})

    async def get(self, obj, cog=None, *, projection: dict = None):
        """Get channel/guild/user. Pass a cog instance in order to return
           cog specific settings"""
        coll = self.obj_to_collection(obj)
        doc = await coll.find_one({"_id": obj.id}, projection)
        if doc and cog:
            try:
                cog_doc = doc["cogs"][cog.__class__.__name__]
                cog_doc.update(_id=doc["_id"])
                return cog_doc
            except KeyError:
                return {}
        return doc or {}

    async def get_flag(self, obj, flag):
        doc = await self.get(obj, projection={"flags": 1, "_id": 0})
        flags = doc.get("flags", [])
        return flag.lower() in flags

    async def set_user(self,
                       user,
                       settings: dict,
                       cog=None,
                       *,
                       operator="$set"):
        """Use dot notation in settings. If cog is passed, the root will be the
        cog's embedded setting document"""
        if cog:
            settings = self.dot_notation(cog, settings)
        await self.users.update_one({"_id": user.id}, {operator: settings},
                                    upsert=True)

    async def set_guild(self,
                        guild,
                        settings: dict,
                        cog=None,
                        *,
                        operator="$set"):
        """Use dot notation in settings. If cog is passed, the root will be the
        cog's embedded setting document"""
        if cog:
            settings = self.dot_notation(cog, settings)
        await self.guilds.update_one({"_id": guild.id}, {operator: settings},
                                     upsert=True)

    async def set_channel(self,
                          channel,
                          settings: dict,
                          cog=None,
                          *,
                          operator="$set"):
        """Use dot notation in settings. If cog is passed, the root will be the
        cog's embedded setting document"""
        if cog:
            settings = self.dot_notation(cog, settings)
        await self.channels.update_one({"_id": channel.id},
                                       {operator: settings},
                                       upsert=True)

    async def set_cog_config(self, cog, settings, *, operator="$set"):
        await self.configs.update_one({"cog_name": cog.__class__.__name__},
                                      {operator: settings})

    async def set(self, obj, settings: dict, cog=None, *, operator="set"):
        """Set channel/guild/user. Use dot notation in settings.
        If cog is passed, the root will be the
        cog's embedded setting document"""
        coll = self.obj_to_collection(obj)
        if cog:
            settings = self.dot_notation(cog, settings)
        if not operator.startswith("$"):
            operator = "$" + operator
        return await coll.update_one({"_id": obj.id}, {operator: settings},
                                     upsert=True)

    async def set_flag(self, obj, **kwargs):
        for flag, value in kwargs.items():
            operator = "$push" if value else "$pull"
            await self.set(obj, {"flags": flag}, operator=operator)

    def get_users_cursor(self, search: dict, cog=None, *, batch_size: int = 0):
        if cog:
            search = self.dot_notation(cog, search)
        cursor = self.users.find(search)
        if batch_size:
            return cursor.batch_size(batch_size)
        return cursor

    def get_guilds_cursor(self,
                          search: dict,
                          cog=None,
                          *,
                          batch_size: int = 0):
        if cog:
            search = self.dot_notation(cog, search)
        cursor = self.guilds.find(search)
        if batch_size:
            return cursor.batch_size(batch_size)
        return cursor

    def get_channels_cursor(self,
                            search: dict,
                            cog=None,
                            *,
                            batch_size: int = 0):
        if cog:
            search = self.dot_notation(cog, search)
        cursor = self.channels.find(search)
        if batch_size:
            return cursor.batch_size(batch_size)
        return cursor

    async def iter(self,
                   collection: str,
                   search: dict,
                   cog=None,
                   *,
                   batch_size: int = 100,
                   subdocs: list = None,
                   **kwargs):
        """Asynchronously iterate over a collection
        Collection can be users/guilds/channels
        Subdocs is a list of strings, being sub document names.
        The deepest subdoc will be the one returned
        """
        coll = self.str_to_collection(collection)
        if cog:
            search = self.dot_notation(cog, search)
        cursor = coll.find(search, **kwargs)
        if batch_size:
            cursor = cursor.batch_size(batch_size)
        async for doc in cursor:
            doc_id = doc["_id"]
            obj = self.get_obj(doc_id, collection)
            if cog:
                doc = doc["cogs"][cog.__class__.__name__]
            if subdocs:
                for d in subdocs:
                    doc = doc[d]
            doc["_id"] = doc_id
            doc["_obj"] = obj
            yield doc

    async def setup_cog(self, cog, default_settings):
        name = cog.__class__.__name__
        doc = await self.configs.find_one({"cog_name": name})
        if not doc:
            default_settings.update(cog_name=name)
            await self.configs.insert_one(default_settings)
            return
        new_keys = 0
        for k, v in default_settings.items():
            if k not in doc:
                new_keys += 1
                doc[k] = v
        if new_keys:
            await self.configs.replace_one({"cog_name": name}, doc)
            print("{} new settings in {}".format(new_keys, name))

    def dot_notation(self, cog, settings):
        d = {}
        for k, v in settings.items():
            d["cogs.{}.{}".format(cog.__class__.__name__, k)] = v
        return d

    def obj_to_collection(self, obj):
        if isinstance(obj, (discord.User, discord.Member)):
            return self.users
        if isinstance(obj, discord.Guild):
            return self.guilds
        if isinstance(obj, discord.TextChannel):
            return self.channels
        raise TypeError("Must be channel/user/guild")

    def str_to_collection(self, name):
        name = name.lower()
        if name not in ["guilds", "users", "channels"]:
            raise TypeError("Collection name be channels/users/guilds")
        return self.db[name]

    def get_obj(self, object_id, name):
        name = name.lower()
        if name.endswith("s"):
            name = name[:-1]
        name = "get_" + name
        return getattr(self.bot, name)(object_id)
