import asyncio
from asyncio.tasks import current_task

import discord
from discord.ext import commands, tasks
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType

from .exceptions import APIError, APIKeyError


class WorldsyncMixin:
    @cog_ext.cog_slash(options=[{
        "name": "enabled",
        "description": "Enable or disable Worldsync",
        "type": SlashCommandOptionType.BOOLEAN,
        "required": True
    }, {
        "name": "world",
        "description": "The world name to use for Worldsync",
        "type": SlashCommandOptionType.STRING,
        "required": False
    }, {
        "name": "world_role",
        "description": "Role to be given to members of the chosen world",
        "type": SlashCommandOptionType.ROLE,
        "required": False,
    }, {
        "name": "ally_role",
        "description": "Role to be given to allies of the chosen world",
        "type": SlashCommandOptionType.ROLE,
        "required": False,
    }])
    async def worldsync(self,
                        ctx,
                        *,
                        enabled,
                        world=None,
                        world_role=None,
                        ally_role=None):
        """Role management based on in game account world"""
        if not ctx.guild:
            return await ctx.send("This command can only be used in servers.",
                                  hidden=True)
        if not ctx.author.guild_permissions.manage_roles:
            return await ctx.send("You need the `manage roles` permission "
                                  "to use this command.")
        doc = await self.bot.database.get(ctx.guild, self)
        doc = doc.get("worldsync", {})
        current = doc.get("enabled", False)
        if not current and not enabled:
            return await ctx.send("Worldsync is aleady disabled.", hidden=True)
        if current and not enabled:
            await self.bot.database.set(ctx.guild,
                                        {"worldsync.enabled": enabled}, self)
            return await ctx.send("Worldsync is now disabled.")
        wid = await self.get_world_id(world)
        if not wid:
            return await ctx.send("Invalid world name")
        if not world_role and not ally_role:
            return await ctx.send(
                "You need to use the role arguments for the bot to do "
                "anytihng.")
        settings = {
            "worldsync.world_id": wid,
            "worldsync.world_role": world_role.id if world_role else None,
            "worldsync.ally_role": ally_role.id if ally_role else None,
            "worldsync.enabled": enabled,
        }
        await self.bot.database.set(ctx.guild, settings, self)
        if enabled:
            await ctx.send("Worldsync is now enabled. Use the same "
                           "command to disable.")
            return await self.sync_worlds(settings, ctx.guild)

    async def worldsync_now(self, ctx):
        """Run the worldsync now"""
        msg = await ctx.send("Starting worldsync." +
                             self.get_emoji(ctx, "loading"))
        doc = await self.bot.database.get(ctx.guild, self)
        worldsync = doc.get("worldsync", {})
        enabled = worldsync.get("enabled", False)
        if not enabled:
            return await ctx.send("Worldsync is not enabled")
        async with ctx.typing():
            await self.sync_worlds(worldsync, ctx.guild)
        await ctx.send("Worldsync complete")
        try:
            await msg.delete()
        except discord.HTTPException:
            pass

    async def get_linked_worlds(self, world):
        endpoint = f"wvw/matches/overview?world={world}"
        results = await self.call_api(endpoint)
        for worlds in results["all_worlds"].values():
            if world in worlds:
                worlds.remove(world)
                return worlds
        return []

    async def worldsync_member(self, member, world_role, ally_role, world_id,
                               linked_worlds):
        try:
            on_world = False
            on_linked = False
            try:
                results = await self.call_api("account", member)
                user_world = results["world"]
                if user_world == world_id:
                    on_world = True
                if user_world in linked_worlds:
                    on_linked = True

            except APIKeyError:
                pass
            except APIError:
                return
            single_role = world_role == ally_role
            if on_world:
                if world_role:
                    if world_role not in member.roles:
                        await member.add_roles(world_role)
                if ally_role:
                    if not single_role and ally_role in member.roles:
                        await member.remove_roles(ally_role)
                return
            if on_linked:
                if ally_role:
                    if ally_role not in member.roles:
                        await member.add_roles(ally_role)
                if world_role:
                    if not single_role and world_role in member.roles:
                        await member.remove_roles(world_role)
                return
            if world_role:
                if world_role in member.roles:
                    await member.remove_roles(world_role)
            if ally_role:
                if ally_role in member.roles:
                    await member.remove_roles(ally_role)
        except Exception:
            pass

    async def sync_worlds(self, doc, guild):
        world_id = doc.get("world_id")
        try:
            linked_worlds = await self.get_linked_worlds(world_id)
        except APIError as e:
            return
        world_role = guild.get_role(doc.get("world_role"))
        ally_role = guild.get_role(doc.get("ally_role"))
        if not world_role and not ally_role:
            return
        for member in guild.members:
            if member.bot:
                continue
            await self.worldsync_member(member, world_role, ally_role,
                                        world_id, linked_worlds)
            await asyncio.sleep(0.1)

    @commands.Cog.listener("on_member_join")
    async def worldsync_on_member_join(self, member):
        if member.bot:
            return
        guild = member.guild
        doc = await self.bot.database.get(guild, self)
        worldsync = doc.get("worldsync", {})
        enabled = worldsync.get("enabled", False)
        if not enabled:
            return
        world_role = guild.get_role(worldsync.get("world_role"))
        ally_role = guild.get_role(worldsync.get("ally_role"))
        if not world_role or not ally_role:
            return
        world_id = worldsync.get("world_id")
        try:
            linked_worlds = await self.get_linked_worlds(world_id)
        except APIError as e:
            return
        await self.worldsync_member(member, world_role, ally_role, world_id,
                                    linked_worlds)

    @tasks.loop(minutes=5)
    async def worldsync_task(self):
        cursor = self.bot.database.iter("guilds", {"worldsync.enabled": True},
                                        self,
                                        subdocs=["worldsync"])
        async for doc in cursor:
            try:
                await self.sync_worlds(doc, doc["_obj"])
            except asyncio.CancelledError:
                return
            except Exception as e:
                pass
