import asyncio
import datetime

import discord
from discord.ext import commands, tasks
from discord.ext.commands.cooldowns import BucketType

from ..exceptions import APIError, APIForbidden, APIKeyError, APINotFound


class SyncGuild:
#### For the "guildsync" group command
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.group(case_insensitive=True, name='guildsync', aliases=['gsync'])
    async def guildsync(self, ctx):
        """Automatic role management based on in-game guilds"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    async def clearsync(self, ctx):
        doc = await self.bot.database.get_guild(ctx.guild, self)
        ranks = doc["sync"].get("ranks")
        for rank in ranks:
            roleobject = discord.utils.get(ctx.guild.roles, id=ranks[rank])
            try:
                await roleobject.delete()
            except discord.Forbidden:
                await ctx.send(
                    f"Don't have permission to delete {rank}")
            except AttributeError:
                # role doesn't exist anymore?
                pass
        await self.bot.database.set_guild(
            ctx.guild, {
                'sync.ranks': {},
                'sync.leader_key': None,
                'sync.setupdone': False,
                'sync.on': False,
                'sync.guildrole': False,
                'sync.name': None,
                'sync.gid': None,
                'sync.purge': False
            }, self)

 ### For the guildsync "CLEAR" command
    @commands.has_permissions(administrator=True)
    @guildsync.command(name='clear')
    async def sync_clear(self, ctx):
        """Wipes settings, roles, and turns sync off."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if not enabled:
            return await ctx.send("No settings to clear.")
        await self.clearsync(ctx)
        await ctx.send("Your settings have been wiped, created roles deleted"
                       " and sync disabled.")

 ### For the guildsync "GUILDROLE" command
    @commands.has_permissions(administrator=True)
    @guildsync.command(name='guildrole', usage='<on|off>', aliases=['grole'])
    async def guildrole_toggle(self, ctx, on_off: bool):
        """Adds a guild tag role for channel management."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        guilddoc = doc['sync']
        guild = self.bot.get_guild(doc['_id'])
        enabled = self.sync_enabled(doc)
        if not enabled:
            await ctx.send(
                "Guildsync needs to be setup before a guildrole can be created.")
            return
        # Find and create name if key doesn't exist.
        if 'name' not in guilddoc:
            info = await self.call_api(f"guild/{guilddoc['gid']}")
            guilddoc['name'] = f"[{info['tag']}]"
            await self.bot.database.set_guild(
                guild, {'sync.name': guilddoc['name']}, self)

        await self.bot.database.set_guild(ctx.guild,
                                          {'sync.guildrole': on_off}, self)
        if on_off:
            # Create role if not enabled already.
            if not guilddoc['guildrole']:
                try:
                    role = await ctx.guild.create_role(
                        name=guilddoc['name'],
                        reason=f"GW2Bot Sync Role [{ctx.prefix}guildsync]",
                        color=discord.Color(self.embed_color))
                    guilddoc['ranks'][guilddoc['name']] = role.id
                except discord.Forbidden:
                    return await ctx.send(f"Couldn't create role {guilddoc['name']}")
                await self.bot.database.set_guild(
                    guild, {'sync.ranks': guilddoc['ranks']}, self)
            msg = ("The guildrole has been created and enabled. Guildsync needs to "
                   "run for members to be synced to the role.")
        else:
            ## Force sync
            doc = await self.bot.database.get_guild(ctx.guild)
            await self.sync_guild_ranks(doc)
            msg = ("Guild role disabled and removed.")
        await ctx.send(msg)

 ### For the guildsync "NOW" command
    @guildsync.command(name='now')
    @commands.cooldown(1, 60, BucketType.user)
    async def sync_now(self, ctx):
        """Force a sync.
        
        This also deletes or creates new roles as needed."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if not enabled:
            return await ctx.send(
                "Guildsync needs to be setup before a synchronization can be forced.")
        await ctx.trigger_typing()
        doc = await self.bot.database.get_guild(ctx.guild)
        await self.sync_guild_ranks(doc)
        await ctx.send("Done.")

 ### For the guildsync "PURGE" command
    @commands.has_permissions(administrator=True)
    @guildsync.command(name='purge', usage='<on|off>')
    async def sync_purge(self, ctx, on_off: bool):
        """Kicks users not in the synced guild.
        
        Users not in the synced guild will be kicked if this is enabled.
        Only exceptions are if a user has a non-guildsync role or has been in the server for less than 48 hours."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if not enabled:
            await ctx.send("Guildsync needs to be setup before purge can be enabled.")
            return
        if on_off:
            await ctx.send(
                "Users without any other role that have been in the server for longer than 48 hours "
                "will be removed during syncs.")
            message = await ctx.send(
                "Are you sure you want to enable this? React ✔ to confirm.")
            await message.add_reaction("✔")

            def waitcheck(wait_react, wait_user):
                return wait_react.emoji == "✔" and wait_user == ctx.author

            try:
                await self.bot.wait_for(
                    'reaction_add', check=waitcheck, timeout=30.0)
            except asyncio.TimeoutError:
                await message.clear_reactions()
                await message.edit(content="You took too long.")
                return
            await message.clear_reactions()
            await ctx.send("Automatic purging enabled.")
            await self.bot.database.set_guild(ctx.guild,
                                              {'sync.purge': on_off}, self)
        else:
            await ctx.send("Automatic purging disabled.")

 ### For the guildsync "SETUP" command
    @commands.has_permissions(administrator=True)
    @guildsync.command(name='setup')
    async def sync_setup(self, ctx):
        """Setup for in-game ranks and discord role synchronization."""
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        if not ctx.guild.me.guild_permissions.manage_roles:
            await ctx.send(
                "I require the 'Manage Roles' permission to do this.")
            return
        doc = await self.bot.database.get_guild(ctx.guild, self)
        if not doc:
            await self.bot.database.set_guild(ctx.guild, {
                'sync.on': False,
                'sync.setupdone': False
            }, self)
            doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if enabled:
            message = await ctx.send(
                "This guild has been setup before. Continuing "
                "will reset existing settings and delete previously "
                "created roles, reply Yes to confirm.")
            try:
                answer = await self.bot.wait_for(
                    'message', timeout=30, check=check)
            except asyncio.TimeoutError:
                return await message.edit(content="No response in time.")
            if answer.content.lower() != 'yes':
                return
            else:
                await self.clearsync(ctx)
        message = await ctx.send(
            "Please type the name of the in-game guild you want to sync "
            "to into the chat now. Please ensure you respond "
            "exactly as it is in-game.")
        try:
            answer = await self.bot.wait_for(
                'message', timeout=30, check=check)
        except asyncio.TimeoutError:
            return await message.edit(content="No response in time.")
        scopes = ['guilds']
        endpoint_id = 'guild/search?name=' + answer.content.replace(' ', '%20')
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
            endpoints = [
                f"guild/{guild_id}/members",
                f"guild/{guild_id}/ranks", f"guild/{guild_id}"
            ]
            results, ranks, info = await self.call_multiple(
                endpoints, ctx.author, scopes)
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name.")
        except APIForbidden:
            return await ctx.send(
                "Only a guild leader is able to perform synchronization.")
        except APIKeyError:
            return await ctx.send(
                "You need to add an API key to your account first.")
        except APIError as e:
            return await self.error_handler(ctx, e)
        roles = {}
        for rank in ranks:
            try:
                role = await ctx.guild.create_role(
                    name=rank['id'],
                    reason=f"GW2Bot Sync Role [{ctx.prefix}guildsync]",
                    color=discord.Color(self.embed_color))
                roles[rank['id']] = role.id
            except discord.Forbidden:
                return await ctx.send(f"Couldn't create role {rank['name']}")
        leader_key_doc = await self.fetch_key(ctx.author)
        await self.bot.database.set_guild(
            ctx.guild, {
                'sync.ranks': roles,
                'sync.leader_key': leader_key_doc['key'],
                'sync.setupdone': True,
                'sync.on': True,
                'sync.guildrole': False,
                'sync.name': f"[{info['tag']}]",
                'sync.gid': guild_id
            }, self)
        guidelines = (
            "**Guidelines:**\n"
            "· Always ensure that GW2Bot is above all synced roles, or the "
            " bot won't be able to assign them.\n"
            "· You can freely modify and change the permissions of the bot created roles.\n"
            "· Only server members with an API key added to the bot will "
            "participate in the sync. No input is required from other users.\n"
            "· New members that add an API key after the sync has been "
            "setup will be synced automatically.\n"
            f"· Users can freely use `{ctx.prefix}key switch` and still be synced.\n"
            "· Guildsync isn't instant; it can take up to 30 minutes before "
            "your settings have been synced. To force a sync, use "
            f"`{ctx.prefix}guildsync now`.")
        await ctx.send(
            "Setup complete. You can toggle synchronization with the "
            f"`{ctx.prefix}guildsync toggle` command.\n"
            "Refer to the guidelines below for additional information.\n"
            "You can find additional help on the website https://gw2bot.info under FAQ.")
        await ctx.send(guidelines)
        doc = await self.bot.database.get_guild(ctx.guild)
        await self.sync_guild_ranks(doc, True)

 ### For the guildsync "TOGGLE" command
    @commands.has_permissions(administrator=True)
    @guildsync.command(name='toggle', usage='<on|off>')
    async def sync_toggle(self, ctx, on_off: bool):
        """Toggles guildsync.
        
        This does not wipe settings."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if not enabled:
            await ctx.send(
                "You need to setup guildsync before synchronization can be toggled.")
            return
        await self.bot.database.set_guild(ctx.guild, {'sync.on': on_off}, self)
        if on_off:
            msg = "Synchronization enabled."
        else:
            msg = "Synchronization disabled."
        await ctx.send(msg)

    ## Gets members
    async def getmembers(self, leader, guild_id):
        scopes = ['guilds']
        try:
            endpoint = f"guild/{guild_id}/members"
            results = await self.call_api(
                endpoint=endpoint, key=leader, scopes=scopes)
            return results
        except Exception as e:
            return None

    ## Adds members to a discord role
    async def add_member_to_role(self, role, member, guild):
        try:
            await member.add_roles(
                role, reason=f"GW2Bot Integration [{ctx.prefix}guildsync]")
        except discord.Forbidden:
            self.log.debug("Permissions error when trying to "
                           f"give {role.name} role to {member.name} user "
                           f"in {guild.name} server.")
            return None
        except AttributeError:
            # role no longer exists - deleted?
            return None

    ## Syncs guild ranks.
    async def sync_guild_ranks(self, doc, initial=False):
        name = self.__class__.__name__
        guild_doc = doc['cogs'][name]['sync']
        enabled = guild_doc.get('on', False)
        purge = guild_doc.get('purge', False)
        guildrole = guild_doc['name'] if guild_doc.get('guildrole',
                                                       False) else None
        if not enabled:
            return
        guild = self.bot.get_guild(doc['_id'])
        if guild is None:
            return
        # Dict of ranks - key is the in-game name of the rank, value is the discord role id
        saved_ranks = guild_doc['ranks']
        # Guild id of the guild used when calling the API
        gid = guild_doc['gid']
        endpoint = f"guild/{gid}/ranks"
        # Discord user ID of the guild leader (their key is used for API calls)
        try:
            leader_key = guild_doc['leader_key']
        # Legacy user that has their discord id saved in the guild doc rather than API key
        except KeyError:
            lid = guild_doc['leader']
            leader = await self.bot.fetch_user(lid)
            try:
                leader_key_doc = await self.fetch_key(leader)
            except APIKeyError:
                ## User removed their key
                await self.bot.database.set_guild(guild,
                                                  {'sync.setupdone': False})
                return
            # Get their API key and save it to the doc
            leader_key = leader_key_doc['key']
            await self.bot.database.set_guild(
                guild, {'sync.leader_key': leader_key}, self)
        scopes = ['guilds']
        # Array to hold discord roles that the server currently has
        current_ranks = []
        # Array to hold discord roles that the server currently has that match up with a in-game rank
        existing_ranks = []
        # Array to hold new in-game ranks that don't have a discord role yet
        new_ranks = []
        # Dict to hold the new dict of ranks to be saved to the guild_doc
        new_saved = {}
        if not initial:
            if len(guild.roles) <= 1:
                return
        # Collect ranks from API
        try:
            ranks = await self.call_api(
                endpoint=endpoint, key=leader_key, scopes=scopes)
        except APIError:
            return
        # Add guild role to ranks dict from API
        if guildrole:
            ranks.append({'id': guildrole})
        for rank in ranks:
            try:
                # Try to find a discord role that matches the rank from API
                discord_role = discord.utils.get(
                    guild.roles, id=guild_doc['ranks'][rank['id']])
                if discord_role:
                    # Append it to our list of existing ranks and to the dict
                    existing_ranks.append(discord_role)
                    new_saved[rank['id']] = discord_role.id
                else:
                    new_ranks.append(rank['id'])
            except KeyError:
                # Can't find it, so this is a new in-game rank.
                new_ranks.append(rank['id'])
        # For each role in our list of role ids from the guild doc, get the discord role
        for role_id in saved_ranks.values():
            discord_role = discord.utils.get(guild.roles, id=role_id)
            current_ranks.append(discord_role)
        # Delete roles that we have on discord that no longer exist in-game.
        to_delete = set(current_ranks) - set(existing_ranks)
        for rank in to_delete:
            try:
                await rank.delete()
            ## Not allowed to delete the role (permissions issue)
            except discord.Forbidden:
                pass
            ## Role doesn't exist somehow?
            except AttributeError:
                pass
        # Create new roles from in-game.
        for role in new_ranks:
            new_role = await guild.create_role(
                name=role,
                reason=f"GW2Bot Sync Role [{ctx.prefix}guildsync]",
                color=discord.Color(self.embed_color))
            new_saved[role] = new_role.id

        # Save the new rank dict to the guild_doc
        guild_doc['ranks'] = new_saved
        await self.bot.database.set_guild(guild, {'sync.ranks': new_saved},
                                          self)
        gw2members = await self.getmembers(leader_key, gid)
        # Array to hold a role list from the roles we now have in the new dict
        role_list = []
        if guildrole:
            guildrole = discord.utils.get(
                guild.roles, id=guild_doc['ranks'][guildrole])
        # Fill the role list
        for role_id in new_saved.values():
            discord_role = discord.utils.get(guild.roles, id=role_id)
            role_list.append(discord_role)
        if gw2members is not None:
            # Iterate through discord's member list
            for member in guild.members:
                rank = None
                if not await self.check_membership(member, gw2members):
                    # If they have a key attached but aren't in the guild, remove any guild sync roles from them
                    if guildrole:
                        role_list.append(guildrole)
                    await self.remove_sync_roles(member, role_list)
                    if purge:
                        membership_duration = (
                            datetime.datetime.utcnow() -
                            member.joined_at).total_seconds()
                        if len(member.
                               roles) <= 1 and membership_duration > 172800:
                            await member.guild.kick(
                                user=member,
                                reason="GW2Bot Integration Guildsync Purge")
                else:
                    key_doc = await self.fetch_key(member)
                    name = key_doc['account_name']
                    # Find the name of their rank in-game
                    for gw2user in gw2members:
                        if gw2user['name'] == name:
                            rank = gw2user['rank']
                    if rank:
                        # Find the id of that rank in the guild_doc and get the discord role
                        try:
                            desired_role = discord.utils.get(
                                member.guild.roles,
                                id=guild_doc["ranks"][rank])
                            # If they don't have that role add it and remove other roles.
                            if desired_role not in member.roles:
                                await self.remove_sync_roles(member, role_list)
                                await self.add_member_to_role(
                                    desired_role, member, guild)
                            # If they don't have the guild role, and guild role is enabled, add it
                            if guildrole:
                                if guildrole not in member.roles:
                                    await self.add_member_to_role(
                                        guildrole, member, guild)
                        except Exception as e:
                            self.log.debug(
                                f"Couldn't get the role object for {member.name} user "
                                f"in {guild.name} server {e}.")
        else:
            self.log.debug(
                f"Unable to obtain member list for {guild.name} server.")

    ## Guild synchronizer
    @tasks.loop(seconds=60)
    async def guild_synchronizer(self):
        cursor = self.bot.database.get_guilds_cursor({
            'sync.on': True,
            'sync.setupdone': True
        },
                                                     self,
                                                     batch_size=30)
        async for doc in cursor:
            try:
                await self.sync_guild_ranks(doc)
            except Exception:
                pass
            await asyncio.sleep(5)

    ## Enables sync
    def sync_enabled(self, doc):
        try:
            enabled = doc['sync'].get('setupdone', False)
        except KeyError:
            enabled = False
        return enabled
    
    ## Checks guild membership
    async def check_membership(self, member, member_list):
        member_doc = await self.bot.database.get(member, self)
        try:
            keys = member_doc['keys']
        except KeyError:
            keys = []
            try:
                keys[0] = await self.fetch_key(member)
            except (APIKeyError, IndexError):
                return False
        for key in keys:
            name = key['account_name']
            for user in member_list:
                if user['name'] == name:
                    return True
        return False

    ## Removes synced roles
    async def remove_sync_roles(self, member, role_list):
        for role in role_list:
            try:
                if role in member.roles:
                    await member.remove_roles(
                        role, reason=f"GW2Bot Integration [{ctx.prefix}guildsync]")
            except discord.Forbidden:
                self.log.debug("Permissions error when trying to "
                               f"remove {role.name} role from {member.name} "
                               f"user in {member.guild.name} server.")
            except discord.HTTPException:
                # usually because user doesn't have the role
                pass

    ## Cog listener
    @commands.Cog.listener('on_member_join')
    async def guildsync_on_member_join(self, member):
        if member.bot:
            return
        guild = member.guild
        doc = await self.bot.database.get(guild)
        name = self.__class__.__name__
        guild_doc = doc['cogs'][name]['sync']
        enabled = guild_doc.get('on', False)
        setupdone = guild_doc.get('setupdone', False)
        if enabled and setupdone:
            await self.sync_guild_ranks(doc)
