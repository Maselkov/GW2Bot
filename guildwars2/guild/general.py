import asyncio
from code import interact
import datetime

import discord
from discord import app_commands
from discord.app_commands import Choice

from ..exceptions import APIError, APIForbidden, APINotFound
from ..utils.chat import embed_list_lines, zero_width_space


async def guild_name_autocomplete(interaction: discord.Interaction,
                                  current: str):
    cog = interaction.command.binding
    bot = cog.bot
    doc = await bot.database.get(interaction.user, cog)
    key = doc.get("key", {})
    if not key:
        return []
    account_key = key["account_name"].replace(".", "_")

    async def cache_guild():
        try:
            results = await cog.call_api("account",
                                         scopes=["account"],
                                         key=key["key"])
        except APIError:
            return choices
        guild_ids = results.get("guilds", [])
        endpoints = [f"guild/{gid}" for gid in guild_ids]
        try:
            guilds = await cog.call_multiple(endpoints)
        except APIError:
            return choices
        guild_list = []
        for guild in guilds:
            guild_list.append({"name": guild["name"], "id": guild["id"]})
        c = {
            "last_update": datetime.datetime.utcnow(),
            "guild_list": guild_list
        }
        await bot.database.set(interaction.user,
                               {f"guild_cache.{account_key}": c}, cog)

    choices = []
    current = current.lower()
    if interaction.guild:
        doc = await bot.database.get(interaction.guild, cog)
        guild_id = doc.get("guild_ingame")
        if guild_id:
            choices.append(
                Choice(name="Server's default guild", value=guild_id))
    doc = await bot.database.get(interaction.user, cog)
    if not key:
        return choices
    cache = doc.get("guild_cache", {}).get(account_key, {})
    if not cache:
        if not choices:
            cache = await cache_guild()
        else:
            asyncio.create_task(cache_guild())
    elif cache["last_update"] < datetime.datetime.utcnow(
    ) - datetime.timedelta(days=7):
        asyncio.create_task(cache_guild())
    if cache:
        choices += [
            Choice(name=guild["name"], value=guild["id"])
            for guild in cache["guild_list"]
            if current in guild["name"].lower()
        ]
    return choices


class ArrowButton(discord.ui.Button):

    def __init__(self, left):
        emoji = "⬅️" if left else "➡️"
        disabled = True if left else False
        super().__init__(style=discord.ButtonStyle.blurple,
                         disabled=disabled,
                         emoji=emoji)
        self.left = left

    async def callback(self, interaction: discord.Interaction):
        if self.left:
            self.view.i -= 1
            if self.view.i == 0:
                self.disabled = True
            self.view.children[1].disabled = False
            await interaction.response.edit_message(
                embed=self.view.embeds[self.view.i], view=self.view)
        else:
            self.view.i += 1
            if self.view.i == len(self.view.embeds) - 1:
                self.disabled = True
            self.view.children[0].disabled = False
            await interaction.response.edit_message(
                embed=self.view.embeds[self.view.i], view=self.view)


class PaginatedEmbeds(discord.ui.View):

    def __init__(self, embeds, user):
        super().__init__()
        self.i = 0
        self.user = user
        self.embeds = embeds
        self.add_item(ArrowButton(left=True)).add_item(ArrowButton(left=False))
        self.response = None

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        await self.response.edit(view=self)


class GeneralGuild:

    guild_group = app_commands.Group(name="guild",
                                     description="Guild related commands")

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
                "Invalid guild name", ephemeral=True)
        except APIForbidden:
            return await interaction.followup.send_message(
                "You don't have enough permissions in game to "
                "use this command",
                ephemeral=True)
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
                                                   ephemeral=True)
        except APIForbidden:
            return await interaction.followup.send(
                "You don't have enough permissions in game to "
                "use this command",
                ephemeral=True)
        embed = discord.Embed(
            colour=await self.get_embed_color(interaction),
            title=base["name"],
        )
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

        embeds = []
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
                                else:
                                    embeds.append(
                                        embed_list_lines(embed,
                                                         lines,
                                                         "> **MEMBERS**",
                                                         inline=True))
                                    lines = [line]
                                    embed = discord.Embed(
                                        title=base["name"],
                                        colour=await
                                        self.get_embed_color(interaction))

            order_id += 1
        embeds.append(
            embed_list_lines(embed, lines, "> **MEMBERS**", inline=True))
        if len(embeds) == 1:
            return await interaction.followup.send(embed=embed)
        for i, embed in enumerate(embeds, start=1):
            embed.set_footer(text="Page {}/{}".format(i, len(embeds)))
        view = PaginatedEmbeds(embeds, interaction.user)
        out = await interaction.followup.send(embed=embeds[0], view=view)
        view.response = out

    @guild_group.command(name="treasury")
    @app_commands.describe(guild="Guild name.")
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_treasury(self, interaction: discord.Interaction,
                             guild: str):
        """Get list of current and needed items for upgrades"""
        await interaction.response.defer()
        endpoints = [f"guild/{guild}", f"guild/{guild}/treasury"]
        try:
            base, treasury = await self.call_multiple(endpoints,
                                                      interaction.user,
                                                      ["guilds"])
        except (IndexError, APINotFound):
            return await interaction.followup.send("Invalid guild name",
                                                   ephemeral=True)
        except APIForbidden:
            return await interaction.followup.send(
                "You don't have enough permissions in game to "
                "use this command",
                ephemeral=True)
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
    @app_commands.describe(log_type="Select the type of log to inspect",
                           guild="Guild name.")
    @app_commands.choices(log_type=[
        Choice(name=it.title(), value=it)
        for it in ["stash", "treasury", "members"]
    ])
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_log(self, interaction: discord.Interaction, log_type: str,
                        guild: str):
        """Get log of last 20 entries of stash/treasury/members"""
        member_list = [
            "invited", "joined", "invite_declined", "rank_change", "kick"
        ]
        # TODO use account cache to speed this up
        await interaction.response.defer()
        endpoints = [f"guild/{guild}", f"guild/{guild}/log/"]
        try:
            base, log = await self.call_multiple(endpoints, interaction.user,
                                                 ["guilds"])
        except (IndexError, APINotFound):
            return await interaction.followup.send("Invalid guild name",
                                                   ephemeral=True)
        except APIForbidden:
            return await interaction.followup.send(
                "You don't have enough permissions in game to "
                "use this command",
                ephemeral=True)

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
                        entry_string = (f"{invited_by} has "
                                        "invited {user} to the guild.")
                    elif entry["type"] == "joined":
                        entry_string = f"{user} has joined the guild."
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
                            entry_string = (
                                f"{changed_by} has changed "
                                f"the role of {user} from {old_rank} "
                                f"to {new_rank}.")
                            entry_string = (
                                "{user} changed his "
                                "role from {old_rank} to {new_rank}.")
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
