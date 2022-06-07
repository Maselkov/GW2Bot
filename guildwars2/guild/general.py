import datetime
from unicodedata import name
from click import Choice

import discord
from discord.app_commands import Choice
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord.ext.commands.errors import BadArgument

from ..exceptions import APIError, APIForbidden, APINotFound
from ..utils.chat import embed_list_lines, zero_width_space


class GeneralGuild:

    guild_group = app_commands.Group(name="guild",
                                     description="Guild related commands")

    async def guild_name_autocomplete(self, interaction: discord.Interaction,
                                      current: str):
        choices = []
        current = current.lower()
        if not current and interaction.guild:
            doc = await self.bot.database.get(interaction.guild, self)
            guild_id = doc.get("guild_ingame")
            if guild_id:
                choices.append(
                    Choice(name="Server's default guild", value=guild_id))
        doc = await self.bot.database.get(interaction.user, self)
        key = doc.get("key", {})
        if not key:
            return choices
        account_key = key["account_name"].replace(".", "_")
        cache = doc.get("guild_cache", {}).get(account_key, {})
        if not cache or cache["last_update"] < datetime.datetime.utcnow(
        ) - datetime.timedelta(days=7):
            try:
                results = await self.call_api("account",
                                              scopes=["account"],
                                              key=key)
            except APIError:
                return choices
            guild_ids = results.get("guilds", [])
            endpoints = [f"guild/{gid}" for gid in guild_ids]
            try:
                guilds = await self.call_multiple(endpoints)
            except APIError:
                return choices
            guild_list = []
            for guild in guilds:
                guild_list.append({"name": guild[name], "id": guild["id"]})
            cache = {
                "last_update": datetime.datetime.utcnow(),
                "guild_list": guild_list
            }
        if cache:
            choices += [
                Choice(name=guild["name"], value=guild["id"])
                for guild in cache["guild_list"]
                if current in guild["name"].lower()
            ]
        return choices

    @guild_group.command(name="info")
    @app_commands.describe(guild="Guild name.")
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_info(self, interaction: discord.Interaction, guild: str):
        """General guild stats"""
        endpoint = "guild/" + guild
        await interaction.response.defer()
        try:
            results = await self.call_api(endpoint, interaction.user,
                                          ["guilds"])
        except (IndexError, APINotFound):
            return await interaction.followup.send_message(
                "Invalid guild name", hidden=True)
        except APIForbidden:
            return await interaction.followup.send_message(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        data = discord.Embed(description='General Info about {0}'.format(
            results["name"]),
                             colour=await self.get_embed_color(interaction))
        data.set_author(name="{} [{}]".format(results["name"], results["tag"]))
        guild_currencies = [
            "influence", "aetherium", "resonance", "favor", "member_count"
        ]
        for cur in guild_currencies:
            if cur == "member_count":
                data.add_field(name='Members',
                               value="{} {}/{}".format(
                                   self.get_emoji(interaction, "friends"),
                                   results["member_count"],
                                   str(results["member_capacity"])))
            else:
                data.add_field(name=cur.capitalize(),
                               value='{} {}'.format(
                                   self.get_emoji(interaction, cur),
                                   results[cur]))
        if "motd" in results:
            data.add_field(name='Message of the day:',
                           value=results["motd"],
                           inline=False)
        data.set_footer(text='A level {} guild'.format(results["level"]))
        await interaction.followup.send(embed=data)

    @guild_group.command(name="members")
    @app_commands.describe(guild="Guild name.")
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_members(self, interaction: discord.Interaction,
                            guild: str):
        """Shows a list of members and their ranks."""
        user = interaction.user
        scopes = ["guilds"]
        await interaction.response.defer()
        endpoints = [
            f"guild/{guild}", f"guild/{guild}/members", f"guild/{guild}/ranks"
        ]
        try:
            base, results, ranks = await self.call_multiple(
                endpoints, user, scopes)
        except (IndexError, APINotFound):
            return await interaction.followup.send("Invalid guild name",
                                                   hidden=True)
        except APIForbidden:
            return await interaction.followup.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        embed = discord.Embed(description=zero_width_space,
                              colour=await self.get_embed_color(interaction))
        embed.set_author(name=base["name"])
        order_id = 1
        # For each order the rank has, go through each member and add it with
        # the current order increment to the embed
        lines = []

        async def get_guild_member_mention(account_name):
            if not interaction.guild:
                return ""
            cursor = self.bot.database.iter(
                "users", {
                    "$or": [{
                        "cogs.GuildWars2.key.account_name": account_name
                    }, {
                        "cogs.GuildWars2.keys.account_name": account_name
                    }]
                })
            async for doc in cursor:
                member = interaction.guild.get_member(doc["_id"])
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
        embed = embed_list_lines(embed, lines, "> **MEMBERS**", inline=True)
        await interaction.followup.send(embed=embed)

    @guild_group.command(name="treasury")
    @app_commands.describe(guild="Guild name.")
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_treasury(self,
                             interaction: discord.Interaction,
                             guild: str = None):
        """Get list of current and needed items for upgrades"""
        await interaction.response.defer()
        guild_id = guild["id"]
        guild_name = guild["name"]
        endpoints = [f"guild/{guild}", f"guild/{guild}/treasury"]
        try:
            base, treasury = await self.call_multiple(endpoints,
                                                      interaction.user,
                                                      ["guilds"])
        except (IndexError, APINotFound):
            return await interaction.followup.send("Invalid guild name",
                                                   hidden=True)
        except APIForbidden:
            return await interaction.followup.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)
        embed = discord.Embed(description=zero_width_space,
                              colour=await self.get_embed_color(interaction))
        embed.set_author(name=base["name"])
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
            return await interaction.followup.send("Treasury is empty!")
        embed = embed_list_lines(embed, lines, "> **TREASURY**", inline=True)
        await interaction.followup.send(embed=embed)

    @guild_group.command(name="log")
    @app_commands.describe(log_type="The type of log to inspect",
                           guild="Guild name.")
    @app_commands.choices(log_type=[
        Choice(name=it.title(), value=it)
        for it in ["stash", "treasury", "members"]
    ])
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_log(self, interaction: discord.Interaction, log_type: str,
                        guild: str):
        """Get log of stash/treasury/members"""
        member_list = [
            "invited", "joined", "invite_declined", "rank_change", "kick"
        ]
        await interaction.response.defer()
        endpoints = [f"guild/{guild}", f"guild/{guild}/log/"]
        try:
            base, log = await self.call_api(endpoints, interaction.user,
                                            ["guilds"])
        except (IndexError, APINotFound):
            return await interaction.followup.send("Invalid guild name",
                                                   hidden=True)
        except APIForbidden:
            return await interaction.followup.send(
                "You don't have enough permissions in game to "
                "use this command",
                hidden=True)

        data = discord.Embed(description=zero_width_space,
                             colour=await self.get_embed_color(interaction))
        data.set_author(name=base["name"])
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
                        item_name = self.gold_to_coins(interaction,
                                                       entry["coins"])
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
            return await interaction.followup.send(
                "No {} log entries yet for {}".format(log_type, base["name"]))
        data = embed_list_lines(data, lines,
                                "> **{0} Log**".format(log_type.capitalize()))
        await interaction.followup.send(embed=data)

    @guild_group.command(name="default")
    @app_commands.describe(guild="Guild name")
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_default(self, ctx, guild: str):
        """ Set your default guild for guild commands on this server."""
        results = await self.call_api(f"guild/{guild}")
        await self.bot.database.set_guild(ctx.guild, {
            "guild_ingame": guild,
        }, self)
        await ctx.send(
            f"Your default guild is now set to {results['name']} for this "
            "server. All commands from the `guild` command group "
            "invoked without a specified guild will default to "
            "this guild. To reset, simply invoke this command "
            "without specifying a guild")
