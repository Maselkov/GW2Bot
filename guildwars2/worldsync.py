import asyncio
import discord

from discord.ext import commands, tasks
from discord import app_commands

from cogs.guildwars2.utils.db import prepare_search
from .exceptions import APIBadRequest, APIError, APIInvalidKey
import time
from discord.app_commands import Choice


class WorldsyncMixin:

    async def worldsync_world_autocomplete(self,
                                           interaction: discord.Interaction,
                                           current: str):
        if not current:
            return []
        query = prepare_search(current)
        query = {"name": query}
        items = await self.db.worlds.find(query).to_list(25)
        return [Choice(name=it["name"], value=str(it["_id"])) for it in items]

    @app_commands.command()
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True, manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(
        enabled="Enable or disable Worldsync",
        world="The world name to use for Worldsync",
        world_role="The role to give to members of the chosen world",
        ally_role="The role to give to allies of the chosen world")
    @app_commands.autocomplete(world=worldsync_world_autocomplete)
    async def worldsync(self,
                        interaction: discord.Interaction,
                        enabled: bool,
                        world: str = None,
                        world_role: discord.Role = None,
                        ally_role: discord.Role = None):
        """Role management based on in game account world"""
        await interaction.response.defer()
        doc = await self.bot.database.get(interaction.guild, self)
        doc = doc.get("worldsync", {})
        current = doc.get("enabled", False)
        if not current and not enabled:
            return await interaction.followup.send(
                "Worldsync is aleady disabled.", ephemeral=True)
        if current and not enabled:
            await self.bot.database.set(interaction.guild,
                                        {"worldsync.enabled": enabled}, self)
            return await interaction.followup.send("Worldsync is now disabled."
                                                   )
        if not world:
            return await interaction.followup.send(
                "You must specify a world name.", ephemeral=True)
        try:
            wid = int(world)
        except ValueError:
            return await interaction.followup.send("Invalid world name",
                                                   ephemeral=True)
        if not world_role and not ally_role:
            return await interaction.followup.send(
                "You need to use the role arguments for the bot to do "
                "anytihng.")
        settings = {
            "worldsync.world_id": wid,
            "worldsync.world_role": world_role.id if world_role else None,
            "worldsync.ally_role": ally_role.id if ally_role else None,
            "worldsync.enabled": enabled,
        }
        await self.bot.database.set(interaction.guild, settings, self)
        if enabled:
            await interaction.followup.send(
                "Worldsync is now enabled. Use the same "
                "command to disable.")
            return await self.sync_worlds(settings, interaction.guild)

    async def worldsync_now(self, ctx):
        """Run the worldsync now"""
        doc = await self.bot.database.get(ctx.guild, self)
        worldsync = doc.get("worldsync", {})
        enabled = worldsync.get("enabled", False)
        if not enabled:
            return
        await self.sync_worlds(worldsync, ctx.guild)

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
        on_world = False
        on_linked = False
        try:
            doc = await self.bot.database.get(member, self)
            keys = doc.get("keys", [])
            key = doc.get("key", {})
            if (key and not keys) or key not in keys:
                keys.append(key)
            checked_accounts = []
            for key_doc in keys:
                if not key_doc:
                    continue
                if key_doc["account_name"] in checked_accounts:
                    continue
                try:
                    await asyncio.sleep(0.3)
                    results = await self.call_api("account",
                                                  key=key_doc["key"])
                    user_world = results["world"]
                    if user_world == world_id:
                        on_world = True
                    if user_world in linked_worlds:
                        on_linked = True
                    checked_accounts.append(key_doc["account_name"])
                except (APIInvalidKey, APIBadRequest):
                    continue
        except APIError:
            return
        single_role = world_role == ally_role
        has_world_role = world_role and world_role in member.roles
        has_ally_role = ally_role and ally_role in member.roles
        if world_role:
            if on_world and not has_world_role:
                await member.add_roles(world_role)
            elif not on_world and has_world_role:
                if not (single_role and on_linked):
                    await member.remove_roles(world_role)
        if ally_role:
            if on_linked and not has_ally_role:
                await member.add_roles(ally_role)
            elif not on_linked and has_ally_role:
                if not (single_role and has_world_role):
                    await member.remove_roles(ally_role)

    async def sync_worlds(self, doc, guild):
        world_id = doc.get("world_id")
        try:
            linked_worlds = await self.get_linked_worlds(world_id)
        except APIError:
            return
        world_role = guild.get_role(doc.get("world_role"))
        ally_role = guild.get_role(doc.get("ally_role"))
        if not world_role and not ally_role:
            return
        for member in guild.members:
            try:
                if member.bot:
                    continue
                await self.worldsync_member(member, world_role, ally_role,
                                            world_id, linked_worlds)
            except discord.HTTPException:
                pass

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
        if not world_role and not ally_role:
            return
        world_id = worldsync.get("world_id")
        try:
            linked_worlds = await self.get_linked_worlds(world_id)
        except APIError:
            return
        await self.worldsync_member(member, world_role, ally_role, world_id,
                                    linked_worlds)

    @tasks.loop(minutes=5)
    async def worldsync_task(self):
        cursor = self.bot.database.iter("guilds", {"worldsync.enabled": True},
                                        self,
                                        subdocs=["worldsync"])
        start = time.time()
        async for doc in cursor:
            try:
                await self.sync_worlds(doc, doc["_obj"])
            except asyncio.CancelledError:
                return
            except Exception:
                pass
        end = time.time()
        self.log.info(f"Worldsync took {end - start} seconds")

    @worldsync_task.before_loop
    async def before_worldsync_task(self):
        await self.bot.wait_until_ready()
