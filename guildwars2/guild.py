import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
import asyncio

from .exceptions import APIError, APIForbidden, APINotFound, APIKeyError


class GuildMixin:
    @commands.group()
    async def guild(self, ctx):
        """Guild related commands.
        """
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @guild.command(name="info")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_info(self, ctx, *, guild_name: str):
        """General guild stats

        Required permissions: guilds
        """
        try:
            endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
            endpoint = "guild/{0}".format(guild_id)
            results = await self.call_api(endpoint, ctx.author, ["guilds"])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description='General Info about your guild',
            colour=self.embed_color)
        data.set_author(name="{} [{}]".format(results["name"], results["tag"]))
        data.add_field(name='Influence', value=results["influence"])
        data.add_field(name='Aetherium', value=results["aetherium"])
        data.add_field(name='Resonance', value=results["resonance"])
        data.add_field(name='Favor', value=results["favor"])
        data.add_field(
            name='Members',
            value="{}/{}".format(results["member_count"],
                                 str(results["member_capacity"])))
        if "motd" in results:
            data.add_field(
                name='Message of the day:',
                value=results["motd"],
                inline=False)
        data.set_footer(text='A level {} guild'.format(results["level"]))
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @guild.command(name="members")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_members(self, ctx, *, guild_name: str):
        """Get list of all members and their ranks.
        Only displays the highest ranks.

        Required permissions: guilds and in game permissions
        """
        user = ctx.author
        scopes = ["guilds"]
        endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
            endpoints = [
                "guild/{}/members".format(guild_id),
                "guild/{}/ranks".format(guild_id)
            ]
            results, ranks = await self.call_multiple(endpoints, user, scopes)
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(description="Members", colour=self.embed_color)
        data.set_author(name=guild_name.title())
        counter = 0
        order_id = 1
        # For each order the rank has, go through each member and add it with
        # the current order increment to the embed
        for order in ranks:
            for member in results:
                # Filter invited members
                if member['rank'] != "invited":
                    member_rank = member['rank']
                    # associate order from /ranks with rank from /members
                    for rank in ranks:
                        if member_rank == rank['id']:
                            if rank['order'] == order_id:
                                if counter < 20:
                                    data.add_field(
                                        name=member['name'],
                                        value=member['rank'])
                                    counter += 1
            order_id += 1
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @guild.command(name="treasury")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_treasury(self, ctx, *, guild_name: str):
        """Get list of current and needed items for upgrades

        Required permissions: guilds and in game permissions"""
        endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
            endpoint = "guild/{0}/treasury".format(guild_id)
            treasury = await self.call_api(endpoint, ctx.author, ["guilds"])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(description="Treasury", colour=self.embed_color)
        data.set_author(name=guild_name.title())
        counter = 0
        item_counter = 0
        amount = 0
        itemlist = []
        for item in treasury:
            res = await self.db.items.find_one({"_id": item["item_id"]})
            itemlist.append(res)
        # Collect amounts
        if treasury:
            for item in treasury:
                if counter < 20:
                    current = item["count"]
                    item_name = itemlist[item_counter]["name"]
                    needed = item["needed_by"]
                    for need in needed:
                        amount = amount + need["count"]
                    if amount != current:
                        data.add_field(
                            name=item_name,
                            value=str(current) + "/" + str(amount),
                            inline=True)
                        counter += 1
                    amount = 0
                    item_counter += 1
        else:
            await ctx.send("Treasury is empty!")
            return
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.group(name="guildsync")
    async def guildsync(self, ctx):
        """Guild synchronization related commands.
        This group of commands allows you to set up a link between your ingame roster and discord.
        When enabled, new roles will be created for each of your ingame ranks, and ingame members are periodically synced to have the correct role in discord."""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    async def clearsync(self, ctx):
        doc = await self.bot.database.get_guild(ctx.guild, self)
        guildroles = ctx.guild.roles
        ranks = doc["sync"].get("ranks")
        for rank in ranks:
            roleobject = discord.utils.get(ctx.guild.roles, name=rank)
            try:
                await roleobject.delete()
            except discord.Forbidden:
                await ctx.send("Don't have permission to delete {0}".format(rank))
        await self.bot.database.set_guild(ctx.guild, {"sync.ranks": [],
                                                      "sync.leader": None,
                                                      "sync.setupdone": False,
                                                      "sync.on": False,
                                                      "sync.gid": None}, self)

    @guildsync.command(name="clear")
    async def sync_clear(self, ctx):
        """Wipes settings and turns sync off."""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = doc["sync"].get("setupdone", False)
        if not enabled:
            await ctx.send("No settings to clear.")
            return
        await self.clearsync(ctx)
        await ctx.send("Done.")


    @guildsync.command(name="setup")
    async def sync_setup(self, ctx):
        """Setup process for ingame roster to discord member list synchronization"""
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        if not ctx.guild.me.guild_permissions.manage_roles:
            await ctx.send("I require the 'Manage Roles' permission to do this.")
            return
        doc = await self.bot.database.get_guild(ctx.guild, self)
        if not doc:
            await self.bot.database.set_guild(ctx.guild, {"sync.on": False, "sync.setupdone": False}, self)
            doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = doc["sync"].get("setupdone", False)
        if enabled:
            message = await ctx.send("You have already ran setup on this guild before, continuing will reset existing settings and delete previously created roles, reply Yes to confirm.")
            try:
                answer = await self.bot.wait_for("message", timeout=30, check=check)
            except asyncio.TimeoutError:
                await message.edit(content="No response in time")
                return
            if answer.content.lower() != "yes":
                return
            else:
                await self.clearsync(ctx)
        message = await ctx.send("Please enter the name of the in-game guild you want to sync to. Please ensure you respond with it exactly as it is in-game.")
        try:
            answer = await self.bot.wait_for("message", timeout=30, check=check)
        except asyncio.TimeoutError:
            await message.edit(content="No response in time")
            return
        scopes = ["guilds"]
        endpoint_id = "guild/search?name=" + answer.content.replace(' ', '%20')
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
            endpoints = [
                "guild/{}/members".format(guild_id),
                "guild/{}/ranks".format(guild_id)
            ]
            results, ranks = await self.call_multiple(endpoints, ctx.author, scopes)
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send("You need to have guild leader permissions ingame to be able to use this synchronization.")
        except APIKeyError:
            return await ctx.send("You need to add an API key to your account first.")
        except APIError as e:
            return await self.error_handler(ctx, e)
        roles = []
        for rank in ranks:
            try:
                role = await ctx.guild.create_role(name=rank["id"], reason="GW2Bot Sync Role")
                roles.append(rank["id"])
            except discord.Forbidden:
                return await ctx.send("Couldn't create role {0}".format(rank["name"]))            
        await self.bot.database.set_guild(ctx.guild, {"sync.ranks": roles,
                                                      "sync.leader": ctx.author.id,
                                                      "sync.setupdone": True,
                                                      "sync.on": True,
                                                      "sync.gid": guild_id}, self)
        await ctx.send("Setup complete, you can toggle the synchronization on and off at any time with $guildsync toggle on/off")



    @guildsync.command(name="toggle")
    async def sync_toggle(self, ctx, on_off: bool):
        """Toggles posting dailies at server reset"""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = doc["sync"].get("setupdone", False)
        if not enabled:
            await ctx.send("You need to run setup before you can toggle synchronization")
            return
        await self.bot.database.set_guild(ctx.guild, {"sync.on": on_off}, self)
        if on_off:
            msg = ("Synchronization enabled.")
        else:
            msg = ("Synchronization disabled.")
        await ctx.send(msg)

    async def getmembers(self, leader, guild_id):
        scopes = ["guilds"]
        try:
            endpoint = "guild/{}/members".format(guild_id)
            results = await self.call_api(endpoint, leader, scopes)
            return results
        except Exception as e:
            print(e)
            return None 

    @guildsync.command(name="now")
    @commands.cooldown(1, 60, BucketType.user)
    async def sync_now(self, ctx):
        """Force a synchronization"""
        doc = await self.bot.database.get_guild(ctx.guild, self)
        enabled = doc["sync"].get("setupdone", False)
        if not enabled:
            await ctx.send("You need to run setup before you can synchronize.")
            return
        await ctx.trigger_typing()
        doc = await self.bot.database.get_guild(ctx.guild)
        await self.sync_members(doc)
        await ctx.send("Done.")

    async def getmembers(self, leader, guild_id):
        scopes = ["guilds"]
        try:
            endpoint = "guild/{}/members".format(guild_id)
            results = await self.call_api(endpoint, leader, scopes)
            return results
        except Exception as e:
            print(e)
            return None 

    async def sync_members(self, doc):
        name = self.__class__.__name__
        guild = self.bot.get_guild(doc["_id"])
        guilddoc = doc["cogs"][name]["sync"]
        leader = await self.bot.get_user_info(guilddoc.get("leader", False))
        gid = guilddoc.get("gid", False)
        gw2members = await self.getmembers(leader, gid)
        guildranks = guilddoc.get("ranks", False)
        rolelist = []
        for rank in guildranks:
            discordrole = discord.utils.get(guild.roles, name=rank)
            rolelist.append(discordrole)
        if gw2members != None:
            for member in guild.members:
                try:
                    keydoc = await self.fetch_key(member)
                    name = keydoc["account_name"]
                    for gw2user in gw2members:
                        if gw2user["name"] == name:
                            rank = gw2user["rank"]
                    if rank:
                        try:
                            desiredrole = discord.utils.get(guild.roles, name=rank)
                            if desiredrole not in member.roles:
                                for role in rolelist:
                                    try:
                                        await member.remove_roles(role, reason="GW2Bot Integration")
                                    except:
                                        print("Permissions error when trying to remove {0} role from {1} user in {2} server.".format(role.name, member.name, guild.name))
                                try:
                                    await member.add_roles(desiredrole, reason="GW2Bot Integration")
                                except discord.Forbidden:
                                    print("Permissions error when trying to give {0} role to {1} user in {2} server.".format(roleobject.name, member.name, guild.name))
                                    pass 
                        except:
                            print("Couldn't get the role object for {0} user in {1} server.".format(member.name, guild.name))                            
                except APIKeyError:
                    pass
        else:
            print("Unable to obtain member list for {0} server.".format(guild.name))            


    async def synchronizer(self):
        while self is self.bot.get_cog("GuildWars2"):
            cursor = self.bot.database.get_guilds_cursor({
                "sync.on": True,
                "sync.setupdone": True
                }, self)
            async for doc in cursor:
                await self.sync_members(doc)
                await asyncio.sleep(600)
                