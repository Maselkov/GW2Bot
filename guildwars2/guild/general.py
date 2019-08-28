import datetime

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord.ext.commands.errors import BadArgument

from ..exceptions import APIError, APIForbidden, APINotFound
from ..utils.chat import embed_list_lines, zero_width_space


class GeneralGuild:
#### For the "GUILD" group command
    @commands.group(case_insensitive=True)
    async def guild(self, ctx):
        """Guild related commands"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

  ### For the guild "INFO" command
    @guild.command(name='info', usage='<guild name>')
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_info(self, ctx, *, guild_name=None):
        """General guild stats.

        Required permission: guilds"""
        # Read preferred guild from DB
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild['id']
            guild_name = guild['name']
            endpoint = f"guild/{guild_id}"
            results = await self.call_api(endpoint, ctx.author, ['guilds'])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name.")
        except APIForbidden:
            return await ctx.send(
                "Only a guild leader can use this command.")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description=f"General Info about {guild_name}",
            colour=await self.get_embed_color(ctx))
        data.set_author(name=f"{results['name']} [{results['tag']}]")
        guild_currencies = ['influence', 'aetherium', 'resonance', 'favor', 'member_count']
        for cur in guild_currencies:
            if cur == 'member_count':
                data.add_field(
                    name="Members",
                    value=f"{self.get_emoji(ctx,'friends')} {results['member_count']}/{str(results['member_capacity'])}")
            else:
                data.add_field(
                    name=cur.capitalize(),
                    value=f"{self.get_emoji(ctx, cur)} {results[cur]}")
        if 'motd' in results:
            data.add_field(
                name="Message of the Day:",
                value=results['motd'],
                inline=False)
        data.set_footer(text=f"A level {results['level']} guild.")
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links.")

  ### For the guild "MEMBERS" command
    @guild.command(name='members', usage='<guild name>')
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_members(self, ctx, *, guild_name=None):
        """Shows a list of members and their ranks.

        Required permissions: guilds, in-game leader"""
        user = ctx.author
        scopes = ['guilds']
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild['id']
            guild_name = guild['name']
            endpoints = [
                f"guild/{guild_id}/members",
                f"guild/{guild_id}/ranks"
            ]
            results, ranks = await self.call_multiple(endpoints, user, scopes)
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name.")
        except APIForbidden:
            return await ctx.send(
                "Only a guild leader can use this command.")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description=zero_width_space,
            colour=await self.get_embed_color(ctx))
        data.set_author(name=guild_name.title())
        order_id = 1
        # For each order the rank has, go through each member and add it with
        # the current order increment to the embed
        lines = []
        for order in ranks:
            for member in results:
                ## Filter invited members
                if member['rank'] != "invited":
                    member_rank = member['rank']
                    ## associate order from /ranks with rank from /members
                    for rank in ranks:
                        if member_rank == rank['id']:
                            if rank['order'] == order_id:
                                line = f"**{member['name']}**\n*{member['rank']}*"
                                if len(str(lines)) + len(line) < 6000:
                                    lines.append(line)
            order_id += 1
        data = embed_list_lines(data, lines, "> **MEMBERS**", inline=True)
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

  ### For the guild "TREASURY" command
    @guild.command(name='treasury', usage='<guild name>')
    @commands.cooldown(1, 20, BucketType.user)
    async def guild_treasury(self, ctx, *, guild_name=None):
        """Gets a list of current/needed items in the treasury.

        Required permissions: guilds and in-game leader"""
        # Read preferred guild from DB
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild['id']
            guild_name = guild['name']
            endpoint = f"guild/{guild_id}/treasury"
            treasury = await self.call_api(endpoint, ctx.author, ['guilds'])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name.")
        except APIForbidden:
            return await ctx.send(
                "Only a guild leader can use this command.")
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description=zero_width_space,
            colour=await self.get_embed_color(ctx))
        data.set_author(name=guild_name.title())
        item_counter = 0
        amount = 0
        lines = []
        itemlist = []
        for item in treasury:
            res = await self.fetch_item(item['item_id'])
            itemlist.append(res)
        # Collect amounts
        if treasury:
            for item in treasury:
                current = item['count']
                item_name = itemlist[item_counter]['name']
                needed = item['needed_by']
                for need in needed:
                    amount = amount + need['count']
                if amount != current:
                    line = f"**{item_name}**\n*{str(current) + '/' + str(amount)}*"
                    if len(str(lines)) + len(line) < 6000:
                        lines.append(line)
                amount = 0
                item_counter += 1
        else:
            await ctx.send("The treasury is empty.")
            return
        data = embed_list_lines(data, lines, "> **TREASURY**", inline=True)
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links.")

  ### For the guild "LOG" command
    @guild.command(name='log', usage='<type> <guild name>')
    @commands.cooldown(1, 10, BucketType.user)
    async def guild_log(self, ctx, log_type, *, guild_name=None):
        """Gets the guild history.
        
        Types: stash, treasury, members
        
        Required permissions: guilds, in-game leader"""
        state = log_type.lower()
        member_list = [
            'invited', 'joined', 'invite_declined', 'rank_change', 'kick'
        ]
        if state not in ('stash', 'treasury', 'members'):
            return await ctx.send_help(ctx.command)
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild:
                raise BadArgument
            guild_id = guild['id']
            guild_name = guild['name']
            endpoint = f"guild/{guild_id}/log/"
            log = await self.call_api(endpoint, ctx.author, ['guilds'])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name.")
        except APIForbidden:
            return await ctx.send(
                "Only a guild leader can use this command.")
        except APIError as e:
            return await self.error_handler(ctx, e)

        data = discord.Embed(
            description=zero_width_space,
            colour=await self.get_embed_color(ctx))
        data.set_author(name=guild_name.title())
        lines = []
        length_lines = 0
        for entry in log:
            if entry['type'] == state:
                time = entry['time']
                timedate = datetime.datetime.strptime(
                    time, "%Y-%m-%dT%H:%M:%S.%fZ").strftime('%d.%m.%Y %H:%M')
                user = entry['user']
                if state == 'stash' or state == 'treasury': # If type == stash/treasury
                    quantity = entry['count']
                    if entry['item_id'] is 0:
                        item_name = self.gold_to_coins(ctx, entry['coins'])
                        quantity = ""
                        multiplier = ""
                    else:
                        itemdoc = await self.fetch_item(entry['item_id'])
                        item_name = itemdoc['name']
                        multiplier = "x"
                    if state == 'stash':
                        if entry['operation'] == 'withdraw':
                            operator = " withdrew"
                        else:
                            operator = " deposited"
                    else:
                        operator = " donated"
                    line = f"**{timedate}**\n*{user} {operator} {quantity}{multiplier} {item_name}*"
                    if length_lines + len(line) < 5500:
                        length_lines += len(line)
                        lines.append(line)
            if state == 'members': # If type == members
                entry_string = ""
                if entry['type'] in member_list:
                    time = entry['time']
                    timedate = datetime.datetime.strptime(
                        time,
                        "%Y-%m-%dT%H:%M:%S.%fZ").strftime('%d.%m.%Y %H:%M')
                    user = entry['user']
                    if entry['type'] == 'invited':
                        invited_by = entry['invited_by']
                        entry_string = f"{invited_by} has invited {user} to the guild."
                    elif entry['type'] == 'joined':
                        entry_string = f"{user} has joined the guild."
                    elif entry['type'] == 'kick':
                        kicked_by = entry["kicked_by"]
                        if kicked_by == user:
                            entry_string = f"{user} has left the guild."
                        else:
                            entry_string = f"{user} has been kicked by {kicked_by}."
                    elif entry['type'] == 'rank_change':
                        old_rank = entry['old_rank']
                        new_rank = entry['new_rank']
                        if 'changed_by' in entry:
                            changed_by = entry['changed_by']
                            entry_string = f"{changed_by} has changed the role of {user} from {old_rank} to {new_rank}."
                        else:
                            entry_string = f"{user} changed his role from {old_rank} to {new_rank}."
                    line = f"**{timedate}**\n*{entry_string}*"
                    if length_lines + len(line) < 5500:
                        length_lines += len(line)
                        lines.append(line)
        if not lines:
            return await ctx.send(f"No {state} log entries yet for {guild_name.title()}.")
        data = embed_list_lines(data, lines, f"> **{state.capitalize()} Log**")
        try:
            await ctx.send(embed=data)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links.")

  ### For the guild "DEFAULT" command
    @guild.command(name='default', usage='<guild name>')
    @commands.guild_only()
    @commands.cooldown(1, 10, BucketType.user)
    @commands.has_permissions(manage_guild=True)
    async def guild_default(self, ctx, *, guild_name=None):
        """Sets the default guild for this server.
        
        Commands will default to the given guild if no guild is provided for guild commands.

        Invoke this command without a guild to remove the default guild."""
        guild = ctx.guild
        if guild_name is None:
            await self.bot.database.set_guild(guild, {
                'guild_ingame': None,
            }, self)
            return await ctx.send(
                "There is now no default guild for "
                "this server. Invoke this command with a guild "
                "name to set a default guild.")
        endpoint_id = 'guild/search?name=' + guild_name.replace(' ', '%20')
        # Guild ID to Guild Name
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name.")
        except APIForbidden:
            return await ctx.send(
                "Only a guild leader can use this command.")
        except APIError as e:
            return await self.error_handler(ctx, e)

        # Write to DB, overwrites existing guild
        await self.bot.database.set_guild(guild, {
            'guild_ingame': guild_id,
        }, self)
        await ctx.send(f"Your default guild has been set to {guild_name.title()} for this server.\n"
                       f"All commands using `{ctx.prefix}guild` "
                       "without a specified guild will default to "
                       "this guild. To reset, simply invoke this command "
                       "again without specifying a guild.")
