import datetime

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from ..exceptions import APIError, APIForbidden, APINotFound


class GeneralGuild:
    @commands.group()
    async def guild(self, ctx):
        """Guild related commands.
        """
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @guild.command(name="info")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_info(self, ctx, *, guild_name=None):
        """General guild stats

        Required permissions: guilds
        """
        # Read preferred guild from DB
        guild_id = await self.get_preferred_guild(ctx, ctx.author)
        # Get Guild name if ID already stored
        if guild_id:
            guild_name = await self.guildid_to_guildname(ctx, guild_id)
        elif guild_name is not None:
            guild_id = await self.guildname_to_guildid(ctx, guild_name)
        else:
            return await self.bot.send_cmd_help(ctx)

        try:
            endpoint = "guild/{0}".format(guild_id)
            results = await self.call_api(endpoint, ctx.author, ["guilds"])
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

    @guild.command(name="members")
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_members(self, ctx, *, guild_name=None):
        """Get list of all members and their ranks.
        Only displays the highest ranks.

        Required permissions: guilds and in game permissions
        """
        user = ctx.author
        scopes = ["guilds"]
        # Read preferred guild from DB
        guild_id = await self.get_preferred_guild(ctx, ctx.author)
        # Get Guild name if ID already stored
        if guild_id:
            guild_name = await self.guildid_to_guildname(ctx, guild_id)
        elif guild_name is not None:
            guild_id = await self.guildname_to_guildid(ctx, guild_name)
        else:
            return await self.bot.send_cmd_help(ctx)
        try:
            endpoints = [
                "guild/{}/members".format(guild_id),
                "guild/{}/ranks".format(guild_id)
            ]
            results, ranks = await self.call_multiple(endpoints, user, scopes)
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
    async def guild_treasury(self, ctx, *, guild_name=None):
        """Get list of current and needed items for upgrades

        Required permissions: guilds and in game permissions"""
        # Read preferred guild from DB
        guild_id = await self.get_preferred_guild(ctx, ctx.author)
        # Get Guild name if ID already stored
        if guild_id:
            guild_name = await self.guildid_to_guildname(ctx, guild_id)
        elif guild_name is not None:
            guild_id = await self.guildname_to_guildid(ctx, guild_name)
        else:
            return await self.bot.send_cmd_help(ctx)

        try:
            endpoint = "guild/{0}/treasury".format(guild_id)
            treasury = await self.call_api(endpoint, ctx.author, ["guilds"])
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

    @guild.command(name="log")
    @commands.cooldown(1, 10, BucketType.user)
    async def guild_log(self, ctx, *, guild_name=None):
        """Get log of last 20 entries of stash
        Required permissions: guilds and in game permissions"""

        # Read preferred guild from DB
        guild_id = await self.get_preferred_guild(ctx, ctx.author)
        # Get Guild name if ID already stored
        if guild_id:
            guild_name = await self.guildid_to_guildname(ctx, guild_id)
        elif guild_name is not None:
            guild_id = await self.guildname_to_guildid(ctx, guild_name)
        else:
            return await self.bot.send_cmd_help(ctx)

        try:
            endpoint = "guild/{0}/log/".format(guild_id)
            log = await self.call_api(endpoint, ctx.author, ["guilds"])
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
            return await ctx.send("No stash log entries yet for {}".format(
                guild_name.title()))
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    @guild.command(name="default")
    @commands.cooldown(1, 10, BucketType.user)
    async def guild_default(self, ctx, *, guild_name=None):
        """ Set your preferred guild for guild commands"""

        guild = ctx.guild
        if guild_name is None:
            await self.bot.database.set_guild(guild, {
                "guild_ingame": "",
            }, self)
            await ctx.send("Your preferred guild is now reset for this server.")
        else:
            guild_id = await self.guildname_to_guildid(ctx, guild_name)
            # Write to DB, overwrites existing guild
            await self.bot.database.set_guild(guild, {
                "guild_ingame": guild_id,
            }, self)

            await ctx.send("Your preferred guild is now set to {0} for this server"
                           .format(guild_name))

    async def get_preferred_guild(self, ctx, user):
        guild = ctx.guild
        guild_id = None
        doc = await self.bot.database.get_guild(guild, self) or {}
        if doc is not None and doc.get("guild_ingame"):
            guild_id = doc.get("guild_ingame")
        return guild_id

    async def guildid_to_guildname(self, ctx, guild_id):
        try:
            endpoint_name = "guild/{0}".format(guild_id)
            results = await self.call_api(endpoint_name)
            guild_name = results["name"]
            return guild_name
        except APIError as e:
            return await self.error_handler(ctx, e)

    async def guildname_to_guildid(self, ctx, guild_name):
        try:
            endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
            return guild_id
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command")
        except APIError as e:
            return await self.error_handler(ctx, e)
