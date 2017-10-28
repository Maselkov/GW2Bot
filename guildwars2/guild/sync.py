import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
import asyncio

from ..exceptions import APIError, APIForbidden, APINotFound, APIKeyError


class SyncGuild:
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.group(name="guildsync")
    async def guildsync(self, ctx):
        """In game guild rank to discord roles synchronization commands
        This group of commands allows you to set up a link between your ingame roster and discord.
        When enabled, new roles will be created for each of your ingame ranks,
        and ingame members are periodically synced to have the
        correct role in discord."""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    async def clearsync(self, ctx):
        doc = await self.bot.database.get_guild(ctx.guild, self)
        ranks = doc["sync"].get("ranks")
        for rank in ranks:
            roleobject = discord.utils.get(ctx.guild.roles, id=ranks[rank])
            try:
                await roleobject.delete()
            except discord.Forbidden:
                await ctx.send(
                    "Don't have permission to delete {0}".format(rank))
            except AttributeError:
                # role doesn't exist anymore?
                pass
        await self.bot.database.set_guild(ctx.guild, {
            "sync.ranks": {},
            "sync.leader": None,
            "sync.setupdone": False,
            "sync.on": False,
            "sync.gid": None
        }, self)

    @guildsync.command(name="clear")
    async def sync_clear(self, ctx):
        """Wipes settings and created roles and turns sync off."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if not enabled:
            return await ctx.send("No settings to clear.")
        await self.clearsync(ctx)
        await ctx.send("Your settings have been wiped, created roles deleted"
                       " and sync disabled.")

    @guildsync.command(name="setup")
    async def sync_setup(self, ctx):
        """Setup process for ingame ranks to discord member roles synchronization"""

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        if not ctx.guild.me.guild_permissions.manage_roles:
            await ctx.send(
                "I require the 'Manage Roles' permission to do this.")
            return
        doc = await self.bot.database.get_guild(ctx.guild, self)
        if not doc:
            await self.bot.database.set_guild(
                ctx.guild, {"sync.on": False,
                            "sync.setupdone": False}, self)
            doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if enabled:
            message = await ctx.send(
                "You have already ran setup on this guild before, continuing "
                "will reset existing settings and delete previously "
                "created roles, reply Yes to confirm.")
            try:
                answer = await self.bot.wait_for(
                    "message", timeout=30, check=check)
            except asyncio.TimeoutError:
                return await message.edit(content="No response in time")
            if answer.content.lower() != "yes":
                return
            else:
                await self.clearsync(ctx)
        message = await ctx.send(
            "Please type the name of the in-game guild you want to sync "
            "to into the chat now. Please ensure you respond with it "
            "exactly as it is in-game.")
        try:
            answer = await self.bot.wait_for(
                "message", timeout=30, check=check)
        except asyncio.TimeoutError:
            return await message.edit(content="No response in time")
        scopes = ["guilds"]
        endpoint_id = "guild/search?name=" + answer.content.replace(' ', '%20')
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
            endpoints = [
                "guild/{}/members".format(guild_id),
                "guild/{}/ranks".format(guild_id)
            ]
            results, ranks = await self.call_multiple(endpoints, ctx.author,
                                                      scopes)
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send(
                "You need to have guild leader permissions ingame to be able "
                "to use this synchronization.")
        except APIKeyError:
            return await ctx.send(
                "You need to add an API key to your account first.")
        except APIError as e:
            return await self.error_handler(ctx, e)
        roles = {}
        for rank in ranks:
            try:
                role = await ctx.guild.create_role(
                    name=rank["id"],
                    reason="GW2Bot Sync Role [$guildsync]",
                    color=discord.Color(self.embed_color))
                roles[rank["id"]] = role.id
            except discord.Forbidden:
                return await ctx.send(
                    "Couldn't create role {0}".format(rank["name"]))
        await self.bot.database.set_guild(ctx.guild, {
            "sync.ranks": roles,
            "sync.leader": ctx.author.id,
            "sync.setupdone": True,
            "sync.on": True,
            "sync.gid": guild_id
        }, self)
        guidelines = (
            "Guild sync requires leader permissions in game\n"
            "Guild sync is tied to your account. If you remove your API key, "
            "guild sync will break\n"
            "**Always ensure that GW2Bot is above the synced roles, or the "
            "bot won't be able to assign them**\n"
            "You can modify and change permissions of the roles created by "
            "the bot.\n"
            "Only server members with API key added to the bot will "
            "participate in the sync, and no input is required from them. "
            "New members which add their API key after sync is "
            "setup will also be synced automatically.\n"
            "Guild sync isn't instant - it can take even 30 minutes before "
            "your settings are synced. To force a sync, you can use "
            "**guildsync now**\n")
        await ctx.send(
            "Setup complete, you can toggle the synchronization on and off "
            "at any time with $guildsync toggle on/off. Now, some guidelines. "
            "In case of issues, refer to this message - you can also find it "
            "on the website https://gw2bot.info under FAQ")
        await ctx.send(guidelines)
        doc = await self.bot.database.get_guild(ctx.guild)
        await self.sync_guild_ranks(doc)

    @guildsync.command(name="toggle")
    async def sync_toggle(self, ctx, on_off: bool):
        """Toggles synchronization on/off - does not wipe settings"""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if not enabled:
            await ctx.send(
                "You need to run setup before you can toggle synchronization")
            return
        await self.bot.database.set_guild(ctx.guild, {"sync.on": on_off}, self)
        if on_off:
            msg = ("Synchronization enabled.")
        else:
            msg = ("Synchronization disabled.")
        await ctx.send(msg)

    @guildsync.command(name="now")
    @commands.cooldown(1, 60, BucketType.user)
    async def sync_now(self, ctx):
        """Force a synchronization, also deletes or creates new ranks as needed."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = self.sync_enabled(doc)
        if not enabled:
            return await ctx.send(
                "You need to run setup before you can synchronize.")
        await ctx.trigger_typing()
        doc = await self.bot.database.get_guild(ctx.guild)
        await self.sync_guild_ranks(doc)
        await ctx.send("Done.")

    async def getmembers(self, leader, guild_id):
        scopes = ["guilds"]
        try:
            endpoint = "guild/{}/members".format(guild_id)
            results = await self.call_api(endpoint, leader, scopes)
            return results
        except Exception as e:
            return None

    async def sync_guild_ranks(self, doc):
        name = self.__class__.__name__
        guilddoc = doc["cogs"][name]["sync"]
        enabled = guilddoc.get("on", False)
        if not enabled:
            return
        guild = self.bot.get_guild(doc["_id"])
        if guild is None:
            return
        savedranks = guilddoc["ranks"]
        gid = guilddoc["gid"]
        endpoint = "guild/{0}/ranks".format(gid)
        lid = guilddoc["leader"]
        scopes = ["guilds"]
        leader = await self.bot.get_user_info(lid)
        currentranks = []
        existingranks = []
        newranks = []
        newsaved = {}
        try:
            ranks = await self.call_api(endpoint, leader, scopes)
        except APIError:
            return
        for rank in ranks:
            try:
                discordrole = discord.utils.get(
                    guild.roles, id=guilddoc["ranks"][rank["id"]])
                if discordrole:
                    existingranks.append(discordrole)
                    newsaved[rank["id"]] = discordrole.id
                else:
                    newranks.append(rank["id"])
            except KeyError:
                newranks.append(rank["id"])
        for role_id in savedranks.values():
            discordrole = discord.utils.get(guild.roles, id=role_id)
            currentranks.append(discordrole)
        todelete = set(currentranks) - set(existingranks)
        for rank in todelete:
            try:
                await rank.delete()
            except discord.Forbidden:
                pass
            except AttributeError:
                pass
        for role in newranks:
            newrole = await guild.create_role(
                name=role,
                reason="GW2Bot Sync Role [$guildsync]",
                color=discord.Color(self.embed_color))
            newsaved[role] = newrole.id
        guilddoc["ranks"] = newsaved
        await self.bot.database.set_guild(guild, {"sync.ranks": newsaved},
                                          self)
        gw2members = await self.getmembers(leader, gid)
        rolelist = []
        for role_id in newsaved.values():
            discordrole = discord.utils.get(guild.roles, id=role_id)
            rolelist.append(discordrole)
        if gw2members is not None:
            for member in guild.members:
                rank = None
                try:
                    keydoc = await self.fetch_key(member)
                    name = keydoc["account_name"]
                    for gw2user in gw2members:
                        if gw2user["name"] == name:
                            rank = gw2user["rank"]
                    if rank:
                        try:
                            desiredrole = discord.utils.get(
                                guild.roles, id=guilddoc["ranks"][rank])
                            if desiredrole not in member.roles:
                                for role in rolelist:
                                    try:
                                        await member.remove_roles(
                                            role,
                                            reason=
                                            "GW2Bot Integration [$guildsync]")
                                    except discord.Forbidden:
                                        self.log.debug(
                                            "Permissions error when trying to "
                                            "remove {0} role from {1} "
                                            "user in {2} server.".format(
                                                role.name, member.name,
                                                guild.name))
                                    except discord.HTTPException:
                                        # usually because user doesn't have role
                                        pass
                                    except AttributeError:
                                        # role no longer exists - deleted?
                                        pass
                                try:
                                    await member.add_roles(
                                        desiredrole,
                                        reason="GW2Bot Integration [$guildsync]"
                                    )
                                except discord.Forbidden:
                                    self.log.debug(
                                        "Permissions error when trying to "
                                        "give {0} role to {1} user "
                                        "in {2} server.".format(
                                            desiredrole.name, member.name,
                                            guild.name))
                                except AttributeError:
                                    # role no longer exists - deleted?
                                    pass
                        except Exception as e:
                            self.log.debug(
                                "Couldn't get the role object for {0} user "
                                "in {1} server {2}.".format(
                                    member.name, guild.name, e))
                except APIKeyError:
                    pass
        else:
            self.log.debug("Unable to obtain member list for {0} server.".
                           format(guild.name))

    async def guild_synchronizer(self):
        while self is self.bot.get_cog("GuildWars2"):
            try:
                cursor = self.bot.database.get_guilds_cursor({
                    "sync.on":
                    True,
                    "sync.setupdone":
                    True
                }, self)
                async for doc in cursor:
                    try:
                        await self.sync_guild_ranks(doc)
                    except:
                        pass
                    await asyncio.sleep(5)
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.log.info("Guildsync terminated")
            except Exception as e:
                self.log.exception("Exception during guildsync: ", exc_info=e)

    def sync_enabled(self, doc):
        try:
            enabled = doc["sync"].get("setupdone", False)
        except KeyError:
            enabled = False
        return enabled
