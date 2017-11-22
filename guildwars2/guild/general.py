import datetime

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord.ext.commands.errors import BadArgument

from ..exceptions import APIError, APIForbidden, APINotFound


class GeneralGuild:
    @commands.group()
    async def guild(self, ctx):
        """Guild related commands."""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @guild.command(name="info", usage="<guild name>")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_info(self, ctx, *, guild_name=None):
        """General guild stats

        Required permissions: guilds
        """
        # Read preferred guild from DB
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild["id"]
            guild_name = guild["name"]
            endpoint = "guild/{0}".format(guild_id)
            results = await self.call_api(endpoint, ctx.author, ["guilds"])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description='General Info about {0}'.format(guild_name),
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

    @guild.command(name="members", usage="<guild name>")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_members(self, ctx, *, guild_name=None):
        """Get list of the first 20 members and their ranks.
        Only displays the highest ranks.

        Required permissions: guilds and in game permissions
        """
        user = ctx.author
        scopes = ["guilds"]
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild["id"]
            guild_name = guild["name"]
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

    @guild.command(name="treasury", usage="<guild name>")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_treasury(self, ctx, *, guild_name=None):
        """Get list of current and needed items for upgrades

        Required permissions: guilds and in game permissions"""
        # Read preferred guild from DB
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild["id"]
            guild_name = guild["name"]
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

    @guild.command(name="log", usage="<guild name>")
    @commands.cooldown(1, 10, BucketType.user)
    async def guild_log(self, ctx, *, guild_name=None):
        """Get log of last 20 entries of stash
        Required permissions: guilds and in game permissions"""
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild["id"]
            guild_name = guild["name"]
            endpoint = "guild/{0}/log/".format(guild_id)
            log = await self.call_api(endpoint, ctx.author, ["guilds"])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(description="Stash Log", colour=self.embed_color)
        data.set_author(name=guild_name.title())
        counter = 0
        for entry in log:
            if entry["type"] == "stash":
                if counter < 20:
                    quantity = entry["count"]
                    time = entry["time"]
                    timedate = datetime.datetime.strptime(
                        time,
                        "%Y-%m-%dT%H:%M:%S.%fZ").strftime('%d.%m.%Y %H:%M')
                    user = entry["user"]
                    if entry["item_id"] is 0:
                        item_name = self.gold_to_coins(entry["coins"])
                        quantity = ""
                        multiplier = ""
                    else:
                        itemdoc = await self.fetch_item(entry["item_id"])
                        item_name = itemdoc["name"]
                        multiplier = "x"
                    if entry["operation"] == "withdraw":
                        operator = " withdrew"
                    else:
                        operator = " deposited"
                    data.add_field(
                        name=timedate,
                        value=user + "{} {}{} {}".format(
                            operator, quantity, multiplier, item_name),
                        inline=False)
                    counter += 1
        if counter == 0:
            return await ctx.send(
                "No stash log entries yet for {}".format(guild_name.title()))
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @guild.command(name="default", usage="<guild name>")
    @commands.guild_only()
    @commands.cooldown(1, 10, BucketType.user)
    @commands.has_permissions(manage_guild=True)
    async def guild_default(self, ctx, *, guild_name=None):
        """ Set your preferred guild for guild commands on this Discord Server.
        Commands from the guild command group invoked
        without a guild name will default to this guild.

        Invoke this command without an argument to reset the default guild.
        """
        guild = ctx.guild
        if guild_name is None:
            await self.bot.database.set_guild(guild, {
                "guild_ingame": None,
            }, self)
            return await ctx.send(
                "Your preferred guild is now reset for "
                "this server. Invoke this command with a guild "
                "name to set a default guild.")
        endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
        # Guild ID to Guild Name
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command")
        except APIError as e:
            return await self.error_handler(ctx, e)

        # Write to DB, overwrites existing guild
        await self.bot.database.set_guild(guild, {
            "guild_ingame": guild_id,
        }, self)
        await ctx.send("Your default guild is now set to {} for this server. "
                       "All commands from the `guild` command group "
                       "invoked without a specified guild will default to "
                       "this guild. To reset, simply invoke this command "
                       "without specifying a guild".format(guild_name.title()))
