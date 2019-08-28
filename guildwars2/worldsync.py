import asyncio

import discord
from discord.ext import commands, tasks

from .exceptions import APIError, APIKeyError

class WorldsyncMixin:
#### For the "WORLDSYNC" group command
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.group(case_insensitive=True, name='worldsync', aliases=['wsync'])
    async def worldsync(self, ctx):
        """Automatic role management based on WvW worlds"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

  ### For the worldsync "ALLYROLE" command
    @worldsync.command(name='allyrole', usage='<world name>', aliases=['arole'])
    async def worldsync_allyrole(self, ctx, role: discord.Role):
        """Sets the role to be given to players linked to the home world.
        
        You can use role mention or ID."""
        await self.bot.database.set(ctx.guild,
                                    {'worldsync.ally_role': role.id}, self)
        await ctx.send("Role set. Make sure the bot has enough permissions "
                       "to grant the role.")

  ### For the worldsync "NOW" command
    @worldsync.command(name='now')
    async def worldsync_now(self, ctx):
        """Forces a sync."""
        doc = await self.bot.database.get(ctx.guild, self)
        worldsync = doc.get('worldsync', {})
        enabled = worldsync.get('enabled', False)
        if not enabled:
            return await ctx.send("Worldsync is not enabled.")
        await self.sync_worlds(worldsync, ctx.guild)
        await ctx.send("Worldsync complete.")

  ### For the worldsync "TOGGLE" command
    @worldsync.command(name='toggle')
    async def worldsync_toggle(self, ctx):
        """Toggles worldsync."""
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        guild = ctx.guild
        doc = await self.bot.database.get(guild, self)
        worldsync = doc.get('worldsync', {})
        enabled = not worldsync.get('enabled', False)
        world_role = guild.get_role(worldsync.get('world_role'))
        ally_role = guild.get_role(worldsync.get('ally_role'))
        world_id = worldsync.get('world_id')
        if not world_role or not ally_role or not world_id and enabled:
            return await ctx.send(
                "You must set your home world, world role, and "
                "ally role before you can enable worldsync.\n```\n"
                f"{ctx.prefix}worldsync world\n"
                f"{ctx.prefix}worldsync worldrole\n"
                f"{ctx.prefix}worldsync allyrole```")
        await self.bot.database.set(guild, {'worldsync.enabled': enabled}, self)
        if enabled:
            await ctx.send("Worldsync enabled.")
            doc = await self.bot.database.get(guild, self)
            return await self.sync_worlds(worldsync, guild)
        await ctx.send("Worldsync disabled.")

  ### For the worldsync "WORLD" command
    @worldsync.command(name='world', usage='<world name>', aliases=['w'])
    async def worldsync_world(self, ctx, *, world):
        """Sets the home world."""
        if not world:
            return await ctx.send_help(ctx.command)
        wid = await self.get_world_id(world)
        if not wid:
            return await ctx.send("Invalid world name.")
        await self.bot.database.set(ctx.guild, {'worldsync.world_id': wid},
                                    self)
        await ctx.send(f"World set! Use `{ctx.prefix}worldsync toggle` to "
                       "enable if you haven't already.")

  ### For the worldsync "WORLDROLE" command
    @worldsync.command(name='worldrole', usage='<role name>', aliases=['wrole'])
    async def worldsync_worldrole(self, ctx, role: discord.Role):
        """Sets the role to be given to players in the home world.
        
        You can use role mention or ID."""
        await self.bot.database.set(ctx.guild,
                                    {'worldsync.world_role': role.id}, self)
        await ctx.send("Role set. Make sure the bot has enough permissions "
                       "to grant the role.")

    ## Gets linked worlds
    async def get_linked_worlds(self, world):
        endpoint = f"wvw/matches/overview?world={world}"
        results = await self.call_api(endpoint)
        for worlds in results['all_worlds'].values():
            if world in worlds:
                worlds.remove(world)
                return worlds

    ## Syncs worlds
    async def sync_worlds(self, doc, guild):
        world_id = doc.get('world_id')
        try:
            linked_worlds = await self.get_linked_worlds(world_id)
        except APIError as e:
            return
        world_role = guild.get_role(doc.get('world_role'))
        ally_role = guild.get_role(doc.get('ally_role'))
        if not world_role or not ally_role:
            return
        for member in guild.members:
            if member.bot:
                continue
            await self.worldsync_member(member, world_role, ally_role,
                                        world_id, linked_worlds)
            await asyncio.sleep(0.25)

    ## Manages members
    async def worldsync_member(self, member, world_role, ally_role, world_id,
                               linked_worlds):
        try:
            on_world = False
            on_linked = False
            try:
                results = await self.call_api('account', member)
                user_world = results['world']
                if user_world == world_id:
                    on_world = True
                if user_world in linked_worlds:
                    on_linked = True

            except APIKeyError:
                pass
            except APIError:
                return
            if on_world:
                if world_role not in member.roles:
                    await member.add_roles(world_role)
                return
            if on_linked:
                if ally_role not in member.roles:
                    await member.add_roles(ally_role)
                return
            if world_role in member.roles:
                await member.remove_roles(world_role)
            if ally_role in member.roles:
                await member.remove_roles(ally_role)
        except:
            pass

    ## When a member joins worldsync
    @commands.Cog.listener('on_member_join')
    async def worldsync_on_member_join(self, member):
        if member.bot:
            return
        guild = member.guild
        doc = await self.bot.database.get(guild, self)
        worldsync = doc.get('worldsync', {})
        enabled = worldsync.get('enabled', False)
        if not enabled:
            return
        world_role = guild.get_role(worldsync.get('world_role'))
        ally_role = guild.get_role(worldsync.get('ally_role'))
        if not world_role or not ally_role:
            return
        world_id = worldsync.get('world_id')
        try:
            linked_worlds = await self.get_linked_worlds(world_id)
        except APIError as e:
            return
        if not linked_worlds:
            return
        await self.worldsync_member(member, world_role, ally_role, world_id,
                                    linked_worlds)

    ## Automatic sync
    @tasks.loop(minutes=5)
    async def worldsync_task(self):
        cursor = self.bot.database.iter(
            'guilds', {'worldsync.enabled': True}, self, subdocs=['worldsync'])
        async for doc in cursor:
            try:
                await self.sync_worlds(doc, doc['_obj'])
            except Exception as e:
                pass
