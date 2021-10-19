import datetime

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord.ext.commands.errors import BadArgument
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType

from ..exceptions import APIError, APIForbidden, APINotFound
from ..utils.chat import embed_list_lines, zero_width_space


class GeneralGuild:
    @cog_ext.cog_subcommand(base="guild",
                            name="info",
                            base_description="Guild related commands",
                            options=[{
                                "name":
                                "guild_name",
                                "description":
                                "Guild name. Can be blank if this "
                                "server has a default "
                                "guild. Required otherwise.",
                                "type":
                                SlashCommandOptionType.STRING,
                                "required":
                                False
                            }])
    async def guild_info(self, ctx, *, guild_name=None):
        """General guild stats"""
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild and not guild_name:
                # TODO guild dropdown
                return await ctx.send(
                    "You need to specify a guild name or "
                    "have a default guild set.",
                    hidden=True)
            guild_id = guild["id"]
            guild_name = guild["name"]
            endpoint = "guild/{0}".format(guild_id)
            results = await self.call_api(endpoint, ctx.author, ["guilds"])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name", hidden=True)
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(
            description='General Info about {0}'.format(guild_name),
            colour=await self.get_embed_color(ctx))
        data.set_author(name="{} [{}]".format(results["name"], results["tag"]))
        guild_currencies = [
            "influence", "aetherium", "resonance", "favor", "member_count"
        ]
        for cur in guild_currencies:
            if cur == "member_count":
                data.add_field(name='Members',
                               value="{} {}/{}".format(
                                   self.get_emoji(ctx, "friends"),
                                   results["member_count"],
                                   str(results["member_capacity"])))
            else:
                data.add_field(name=cur.capitalize(),
                               value='{} {}'.format(self.get_emoji(ctx, cur),
                                                    results[cur]))
        if "motd" in results:
            data.add_field(name='Message of the day:',
                           value=results["motd"],
                           inline=False)
        data.set_footer(text='A level {} guild'.format(results["level"]))
        await ctx.send(embed=data)

    @cog_ext.cog_subcommand(base="guild",
                            name="members",
                            base_description="Guild related commands",
                            options=[{
                                "name":
                                "guild_name",
                                "description":
                                "Guild name. Can be blank if this "
                                "server has a default "
                                "guild. Required otherwise.",
                                "type":
                                SlashCommandOptionType.STRING,
                                "required":
                                False
                            }])
    async def guild_members(self, ctx, *, guild_name=None):
        """Shows a list of members and their ranks."""
        user = ctx.author
        scopes = ["guilds"]
        await ctx.defer()
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild and not guild_name:
                # TODO guild dropdown
                return await ctx.send(
                    "You need to specify a guild name or "
                    "have a default guild set.",
                    hidden=True)
            guild_id = guild["id"]
            guild_name = guild["name"]
            endpoints = [
                "guild/{}/members".format(guild_id),
                "guild/{}/ranks".format(guild_id)
            ]
            results, ranks = await self.call_multiple(endpoints, user, scopes)
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name", hidden=True)
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(description=zero_width_space,
                             colour=await self.get_embed_color(ctx))
        data.set_author(name=guild_name.title())
        order_id = 1
        # For each order the rank has, go through each member and add it with
        # the current order increment to the embed
        lines = []

        async def get_guild_member_mention(account_name):
            cursor = self.bot.database.iter(
                "users", {
                    "$or": [{
                        "cogs.GuildWars2.key.account_name": account_name
                    }, {
                        "cogs.GuildWars2.keys.account_name": account_name
                    }]
                })
            async for doc in cursor:
                member = ctx.guild.get_member(doc["_id"])
                if member:
                    return member.mention
            return ""

        for order in ranks:
            for member in results:
                # Filter invited members
                if member['rank'] != "invited":
                    member_rank = member['rank']
                    # associate order from /ranks with rank from /members
                    for rank in ranks:
                        if member_rank == rank['id']:
                            if rank['order'] == order_id:
                                mention = await get_guild_member_mention(
                                    member["name"])
                                if mention:
                                    mention = f" - {mention}"
                                line = "**{}**{}\n*{}*".format(
                                    member['name'], mention, member['rank'])
                                if len(str(lines)) + len(line) < 6000:
                                    lines.append(line)
            order_id += 1
        data = embed_list_lines(data, lines, "> **MEMBERS**", inline=True)
        await ctx.send(embed=data)

    @cog_ext.cog_subcommand(base="guild",
                            name="treasury",
                            base_description="Guild related commands",
                            options=[{
                                "name":
                                "guild_name",
                                "description":
                                "Guild name. Can be blank if this "
                                "server has a default "
                                "guild. Required otherwise.",
                                "type":
                                SlashCommandOptionType.STRING,
                                "required":
                                False
                            }])
    async def guild_treasury(self, ctx, *, guild_name=None):
        """Get list of current and needed items for upgrades"""
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild and not guild_name:
                # TODO guild dropdown
                return await ctx.send(
                    "You need to specify a guild name or "
                    "have a default guild set.",
                    hidden=True)
            guild_id = guild["id"]
            guild_name = guild["name"]
            endpoint = "guild/{0}/treasury".format(guild_id)
            treasury = await self.call_api(endpoint, ctx.author, ["guilds"])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name", hidden=True)
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        except APIError as e:
            return await self.error_handler(ctx, e)
        data = discord.Embed(description=zero_width_space,
                             colour=await self.get_embed_color(ctx))
        data.set_author(name=guild_name.title())
        item_counter = 0
        amount = 0
        lines = []
        itemlist = []
        for item in treasury:
            res = await self.fetch_item(item["item_id"])
            itemlist.append(res)
        # Collect amounts
        if treasury:
            for item in treasury:
                current = item["count"]
                item_name = itemlist[item_counter]["name"]
                needed = item["needed_by"]
                for need in needed:
                    amount = amount + need["count"]
                if amount != current:
                    line = "**{}**\n*{}*".format(
                        item_name,
                        str(current) + "/" + str(amount))
                    if len(str(lines)) + len(line) < 6000:
                        lines.append(line)
                amount = 0
                item_counter += 1
        else:
            await ctx.send("Treasury is empty!")
            return
        data = embed_list_lines(data, lines, "> **TREASURY**", inline=True)
        await ctx.send(embed=data)

    @cog_ext.cog_subcommand(base="guild",
                            name="log",
                            base_description="Guild related commands",
                            options=[{
                                "name":
                                "log_type",
                                "description":
                                "The type of log to inspect"
                                "guild. Required otherwise.",
                                "type":
                                SlashCommandOptionType.STRING,
                                "required":
                                True,
                                "choices": [{
                                    "name": "Stash",
                                    "value": "stash"
                                }, {
                                    "name": "Treasury",
                                    "value": "treasury"
                                }, {
                                    "name": "Roster",
                                    "value": "members"
                                }]
                            }, {
                                "name":
                                "guild_name",
                                "description":
                                "Guild name. Can be blank if this "
                                "server has a default "
                                "guild. Required otherwise.",
                                "type":
                                SlashCommandOptionType.STRING,
                                "required":
                                False
                            }])
    async def guild_log(self, ctx, log_type, *, guild_name=None):
        """Get log of stash/treasury/members"""
        member_list = [
            "invited", "joined", "invite_declined", "rank_change", "kick"
        ]
        try:
            guild = await self.get_guild(ctx, guild_name=guild_name)
            if not guild and not guild_name:
                # TODO guild dropdown
                return await ctx.send(
                    "You need to specify a guild name or "
                    "have a default guild set.",
                    hidden=True)
            guild_id = guild["id"]
            guild_name = guild["name"]
            endpoint = "guild/{0}/log/".format(guild_id)
            log = await self.call_api(endpoint, ctx.author, ["guilds"])
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name", hidden=True)
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        except APIError as e:
            return await self.error_handler(ctx, e)

        data = discord.Embed(description=zero_width_space,
                             colour=await self.get_embed_color(ctx))
        data.set_author(name=guild_name.title())
        lines = []
        length_lines = 0
        for entry in log:
            if entry["type"] == log_type:
                time = entry["time"]
                timedate = datetime.datetime.strptime(
                    time, "%Y-%m-%dT%H:%M:%S.%fZ").strftime('%d.%m.%Y %H:%M')
                user = entry["user"]
                if log_type == "stash" or log_type == "treasury":
                    quantity = entry["count"]
                    if entry["item_id"] == 0:
                        item_name = self.gold_to_coins(ctx, entry["coins"])
                        quantity = ""
                        multiplier = ""
                    else:
                        itemdoc = await self.fetch_item(entry["item_id"])
                        item_name = itemdoc["name"]
                        multiplier = "x"
                    if log_type == "stash":
                        if entry["operation"] == "withdraw":
                            operator = " withdrew"
                        else:
                            operator = " deposited"
                    else:
                        operator = " donated"
                    line = "**{}**\n*{}*".format(
                        timedate, user + "{} {}{} {}".format(
                            operator, quantity, multiplier, item_name))
                    if length_lines + len(line) < 5500:
                        length_lines += len(line)
                        lines.append(line)
            if log_type == "members":
                entry_string = ""
                if entry["type"] in member_list:
                    time = entry["time"]
                    timedate = datetime.datetime.strptime(
                        time,
                        "%Y-%m-%dT%H:%M:%S.%fZ").strftime('%d.%m.%Y %H:%M')
                    user = entry["user"]
                    if entry["type"] == "invited":
                        invited_by = entry["invited_by"]
                        entry_string = "{} has invited {} to the guild.".format(
                            invited_by, user)
                    elif entry["type"] == "joined":
                        entry_string = "{} has joined the guild.".format(user)
                    elif entry["type"] == "kick":
                        kicked_by = entry["kicked_by"]
                        if kicked_by == user:
                            entry_string = "{} has left the guild.".format(
                                user)
                        else:
                            entry_string = "{} has been kicked by {}.".format(
                                user, kicked_by)
                    elif entry["type"] == "rank_change":
                        old_rank = entry["old_rank"]
                        new_rank = entry["new_rank"]
                        if "changed_by" in entry:
                            changed_by = entry["changed_by"]
                            entry_string = "{} has changed the role of {} from {} to {}.".format(
                                changed_by, user, old_rank, new_rank)
                        else:
                            entry_string = "{} changed his role from {} to {}.".format(
                                user, old_rank, new_rank)
                    line = "**{}**\n*{}*".format(timedate, entry_string)
                    if length_lines + len(line) < 5500:
                        length_lines += len(line)
                        lines.append(line)
        if not lines:
            return await ctx.send("No {} log entries yet for {}".format(
                log_type, guild_name.title()))
        data = embed_list_lines(data, lines,
                                "> **{0} Log**".format(log_type.capitalize()))
        await ctx.send(embed=data)

    @cog_ext.cog_subcommand(base="guild",
                            name="default",
                            base_description="Guild related commands",
                            options=[{
                                "name": "guild_name",
                                "description":
                                "Guild name. Leave blank to reset",
                                "type": SlashCommandOptionType.STRING,
                                "required": False
                            }])
    async def guild_default(self, ctx, *, guild_name=None):
        """ Set your default guild for guild commands on this server."""
        if guild_name is None:
            await self.bot.database.set_guild(ctx.guild, {
                "guild_ingame": None,
            }, self)
            return await ctx.send(
                "Your default guild is now reset for "
                "this server. Invoke this command with a guild "
                "name to set a default guild.")
        endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
        # Guild ID to Guild Name
        try:
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name", hidden=True)
        except APIForbidden:
            return await ctx.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        except APIError as e:
            return await self.error_handler(ctx, e)

        # Write to DB, overwrites existing guild
        await self.bot.database.set_guild(ctx.guild, {
            "guild_ingame": guild_id,
        }, self)
        await ctx.send(
            f"Your default guild is now set to {guild_name.title()} for this server. "
            "All commands from the `guild` command group "
            "invoked without a specified guild will default to "
            "this guild. To reset, simply invoke this command "
            "without specifying a guild")

    async def get_guild(self, ctx, guild_id=None, guild_name=None):
        if guild_name:
            endpoint_id = "guild/search?name=" + guild_name.replace(' ', '%20')
            guild_id = await self.call_api(endpoint_id)
            guild_id = guild_id[0]
        elif not guild_id:
            if not ctx.guild:
                return None
            doc = await self.bot.database.get_guild(ctx.guild, self) or {}
            guild_id = doc.get("guild_ingame")
        if not guild_id:
            return None
        endpoint = "guild/{0}".format(guild_id)
        return await self.call_api(endpoint, ctx.author, ["guilds"])
