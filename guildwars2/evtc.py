import asyncio
import datetime
import secrets
from typing import Union

import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.app_commands import Choice
from .exceptions import APIError
from .utils.chat import (embed_list_lines, en_space, magic_space,
                         zero_width_space)

UTC_TZ = datetime.timezone.utc

BASE_URL = "https://dps.report/"
UPLOAD_URL = BASE_URL + "uploadContent"
JSON_URL = BASE_URL + "getJson"
TOKEN_URL = BASE_URL + "getUserToken"
ALLOWED_FORMATS = (".evtc", ".zevtc", ".zip")


class EvtcGuildSelectionViewSelect(discord.ui.Select):

    def __init__(self, cog, guilds):
        self.cog = cog
        options = []
        for guild in guilds:
            name = f"{guild['name']} [{guild['tag']}]"
            options.append(discord.SelectOption(label=name, value=guild["id"]))
        super().__init__(options=options,
                         placeholder="Select guilds",
                         min_values=1,
                         max_values=len(options))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="This channel is now a destination for EVTC logs. "
            "Logs uploaded using third-party utilities with your GW2Bot "
            "EVTC API key will be posted here. You can have multiple "
            "destinations at the same time. DMs also work.\nYou can always "
            "remove it using `/evtc_automation remove_destinations`",
            view=None)
        self.view.selected_guilds = self.values
        self.view.stop()


class EvtcGuildSelectionView(discord.ui.View):

    def __init__(self, cog, guilds):
        super().__init__(timeout=60)
        self.cog = cog
        self.add_item(EvtcGuildSelectionViewSelect(cog, guilds))
        self.selected_guilds = []
        self.skip = False

    @discord.ui.button(label='Next',
                       style=discord.ButtonStyle.blurple,
                       emoji="➡️")
    async def confirm(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        await interaction.response.edit_message(
            content="This channel is now a destination for EVTC logs. "
            "Logs uploaded using third-party utilities with your GW2Bot "
            "EVTC API key will be posted here. You can have multiple "
            "destinations at the same time. DMs also work.\nYou can always "
            "remove it using `/evtc autopost remove_destinations`",
            view=None)
        self.skip = True
        self.stop()


class EvtcAutouploadDestinationsSelect(discord.ui.Select):

    def __init__(self, cog, channels, destinations):
        self.cog = cog
        self.destinations = destinations
        options = []
        for i, channel in enumerate(channels):
            if isinstance(channel, discord.DMChannel):
                name = "DM"
            else:
                if not channel:
                    name = "Inaccessible Channel"
                name = f"{channel.guild.name} - {channel.name}"
            options.append(discord.SelectOption(label=name, value=str(i)))
        super().__init__(options=options,
                         placeholder="Select destinations to remove",
                         min_values=1,
                         max_values=len(options))

    async def callback(self, interaction: discord.Interaction):
        choices = [self.destinations[int(i)] for i in self.values]
        for choice in choices:
            await self.cog.db.evtc.destinations.delete_one(
                {"_id": choice["_id"]})
        await interaction.response.edit_message(
            content="Removed selected destinations.", view=None)
        self.view.stop()


# class EvtcAutouploadRemoveDestinationsView(discord.ui.View):
#     def __init__(self, cog, channels, destinations):
#         self.destinations = destinations
#         self.add_item())
#         super().__init__(timeout=60)


class EvtcMixin:

    evtc_automation_group = app_commands.Group(
        name="evtc_automation",
        description="Character relating to automating EVTC processing")

    autopost_group = app_commands.Group(
        name="autopost",
        description="Automatically post processed EVTC logs uploaded by "
        "third party utilities",
        parent=evtc_automation_group)

    async def get_dpsreport_usertoken(self, user):
        doc = await self.bot.database.get(user, self)
        token = doc.get("dpsreport_token")
        if not token:
            try:
                async with self.session.get(TOKEN_URL) as r:
                    data = await r.json()
                    token = data["userToken"]
                    await self.bot.database.set(user,
                                                {"dpsreport_token": token},
                                                self)
                    return token
            except Exception:
                return None

    async def upload_log(self, file, user):
        params = {"json": 1}
        token = await self.get_dpsreport_usertoken(user)
        if token:
            params["userToken"] = token
        data = aiohttp.FormData()
        data.add_field("file", await file.read(), filename=file.filename)
        async with self.session.post(UPLOAD_URL, data=data,
                                     params=params) as r:
            resp = await r.json()
            error = resp["error"]
            if error:
                raise APIError(error)
            return resp

    async def find_duplicate_dps_report(self, doc):
        margin_of_error = datetime.timedelta(seconds=10)
        doc = await self.db.encounters.find_one({
            "boss_id": doc["boss_id"],
            "players": {
                "$eq": doc["players"]
            },
            "date": {
                "$gte": doc["date"] - margin_of_error,
                "$lt": doc["date"] + margin_of_error
            },
            "start_date": {
                "$gte": doc["start_date"] - margin_of_error,
                "$lt": doc["start_date"] + margin_of_error
            },
        })
        return True if doc else False

    async def get_encounter_data(self, encounter_id):
        async with self.session.get(JSON_URL, params={"id":
                                                      encounter_id}) as r:
            return await r.json()

    async def upload_embed(self, destination, data, permalink):
        force_emoji = True if not destination else False
        lines = []
        targets = data["phases"][0]["targets"]
        group_dps = 0
        wvw = data["triggerID"] == 1
        for target in targets:
            group_dps += sum(p["dpsTargets"][target][0]["dps"]
                             for p in data["players"])

        def get_graph(percentage):
            bar_count = round(percentage / 5)
            bars = ""
            bars += "▀" * bar_count
            bars += "━" * (20 - bar_count)
            return bars

        def get_dps(player):
            bars = ""
            dps = player["dps"]
            if not group_dps or not dps:
                percentage = 0
            else:
                percentage = round(100 / group_dps * dps)
            bars = get_graph(percentage)
            bars += f"` **{dps}** DPS | **{percentage}%** of group DPS"
            return bars

        players = []
        for player in data["players"]:
            dps = 0
            for target in targets:
                dps += player["dpsTargets"][target][0]["dps"]
            player["dps"] = dps
            players.append(player)
        players.sort(key=lambda p: p["dps"], reverse=True)
        for player in players:
            down_count = player["defenses"][0]["downCount"]
            prof = self.get_emoji(destination,
                                  player["profession"],
                                  force_emoji=True)
            line = f"{prof} **{player['name']}** *({player['account']})*"
            if down_count:
                line += (
                    f" | {self.get_emoji(destination, 'downed', force_emoji=True)}Downed "
                    f"count: **{down_count}**")
            lines.append(line)
        dpses = []
        charater_name_max_length = 19
        for player in players:
            line = self.get_emoji(destination,
                                  player["profession"],
                                  fallback=True,
                                  fallback_fmt="",
                                  force_emoji=True)
            align = (charater_name_max_length - len(player["name"])) * " "
            line += "`" + player["name"] + align + get_dps(player)
            dpses.append(line)
        dpses.append(f"> Group DPS: **{group_dps}**")
        color = discord.Color.green(
        ) if data["success"] else discord.Color.red()
        minutes, seconds = data["duration"].split()[:2]
        minutes = int(minutes[:-1])
        seconds = int(seconds[:-1])
        duration_time = (minutes * 60) + seconds
        duration = f"**{minutes}** minutes, **{seconds}** seconds"
        embed = discord.Embed(title="DPS Report",
                              description="Encounter duration: " + duration,
                              url=permalink,
                              color=color)
        boss_lines = []
        for target in targets:
            target = data["targets"][target]
            if data["success"]:
                health_left = 0
            else:
                percent_burned = target["healthPercentBurned"]
                health_left = 100 - percent_burned
            health_left = round(health_left, 2)
            if len(targets) > 1:
                boss_lines.append(f"**{target['name']}**")
            boss_lines.append(f"Health: **{health_left}%**")
            boss_lines.append(get_graph(health_left))
        embed.add_field(name="> **BOSS**", value="\n".join(boss_lines))
        buff_lines = []
        sought_buffs = ["Might", "Fury", "Quickness", "Alacrity", "Protection"]
        buffs = []
        for buff in sought_buffs:
            for key, value in data["buffMap"].items():
                if value["name"] == buff:
                    buffs.append({
                        "name": value["name"],
                        "id": int(key[1:]),
                        "stacking": value["stacking"]
                    })
                    break
        separator = 2 * en_space
        line = zero_width_space + (en_space * (charater_name_max_length + 6))
        icon_line = line
        blank = self.get_emoji(destination, "blank", force_emoji=True)
        first = True
        for buff in sought_buffs:
            if first and not blank:
                icon_line = icon_line[:-2]
            if not first:
                if blank:
                    icon_line += blank + blank
                else:
                    icon_line += separator + (en_space * 4)
            icon_line += self.get_emoji(destination,
                                        buff,
                                        fallback=True,
                                        fallback_fmt="{:1.1}",
                                        force_emoji=True)
            first = False
        groups = []
        for player in players:
            if player["group"] not in groups:
                groups.append(player["group"])
        if len(groups) > 1:
            players.sort(key=lambda p: p["group"])
        current_group = None
        for player in players:
            if "buffUptimes" not in player:
                continue
            if len(groups) > 1:
                if not current_group or player["group"] != current_group:
                    current_group = player["group"]
                    buff_lines.append(f"> **GROUP {current_group}**")
            line = "`"
            line = self.get_emoji(destination,
                                  player["profession"],
                                  fallback=True,
                                  fallback_fmt="",
                                  force_emoji=True)
            align = (3 + charater_name_max_length - len(player["name"])) * " "
            line += "`" + player["name"] + align
            for buff in buffs:
                for buff_uptime in player["buffUptimes"]:
                    if buff["id"] == buff_uptime["id"]:
                        uptime = str(
                            round(buff_uptime["buffData"][0]["uptime"],
                                  1)).rjust(5)
                        break
                else:
                    uptime = "0"
                if not buff["stacking"]:
                    uptime += "%"
                line += uptime
                line += separator + ((6 - len(uptime)) * magic_space)
            line += '`'
            buff_lines.append(line.strip())
        if not wvw:
            embed = embed_list_lines(embed, lines, "> **PLAYERS**")
        if wvw:
            dpses = dpses[:15]
        embed = embed_list_lines(embed, dpses, "> **DPS**")
        embed.add_field(name="> **BUFFS**", value=icon_line)

        embed = embed_list_lines(embed, buff_lines, zero_width_space)
        boss = self.gamedata["bosses"].get(str(data["triggerID"]))
        date_format = "%Y-%m-%d %H:%M:%S %z"
        date = datetime.datetime.strptime(data["timeEnd"] + "00", date_format)
        start_date = datetime.datetime.strptime(data["timeStart"] + "00",
                                                date_format)
        date = date.astimezone(datetime.timezone.utc)
        start_date = start_date.astimezone(datetime.timezone.utc)
        doc = {
            "boss_id": data["triggerID"],
            "start_date": start_date,
            "date": date,
            "players":
            sorted([player["account"] for player in data["players"]]),
            "permalink": permalink,
            "success": data["success"],
            "duration": duration_time
        }
        duplicate = await self.find_duplicate_dps_report(doc)
        if not duplicate:
            await self.db.encounters.insert_one(doc)
        embed.timestamp = date
        embed.set_footer(text="Recorded at", icon_url=self.bot.user.avatar.url)
        if boss:
            embed.set_author(name=data["fightName"], icon_url=boss["icon"])
        return embed

    @app_commands.command(name="evtc")
    @app_commands.checks.bot_has_permissions(embed_links=True)
    @app_commands.describe(
        file="EVTC file to process. Accepted formats: .evtc, .zip, .zevtc")
    async def evtc(self, interaction: discord.Interaction,
                   file: discord.Attachment):
        """Process an EVTC combat log in an attachment"""
        if not file.filename.endswith(ALLOWED_FORMATS):
            return await interaction.response.send_message(
                "The attachment seems not to be of a correct filetype.\n"
                f"Allowed file extensions: `{', '.join(ALLOWED_FORMATS)}`",
                ephemeral=True)
        await interaction.response.defer()
        await self.process_evtc([file], interaction.user, interaction.followup)

    @evtc_automation_group.command(name="channel")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True,
                                         manage_channels=True)
    @app_commands.checks.bot_has_permissions(embed_links=True,
                                             use_external_emojis=True)
    @app_commands.describe(
        enabled="Disable or enable this feature on the specificed channel",
        channel="The target channel",
        autodelete="Delete original message after processing the EVTC log")
    async def evtc_channel(self, interaction: discord.Interaction,
                           enabled: bool, channel: discord.TextChannel,
                           autodelete: bool):
        """Sets a channel to be automatically used to process EVTC logs
        posted within"""
        doc = await self.bot.database.get(channel, self)
        enabled = not doc.get("evtc.enabled", False)
        await self.bot.database.set(channel, {
            "evtc.enabled": enabled,
            "evtc.autodelete": autodelete
        }, self)
        if enabled:
            msg = ("Automatic EVTC processing enabled. Simply upload the file "
                   f"wish to be processed in {channel.mention}, while "
                   "@mentioning the bot in the same message.. Accepted "
                   f"formats: `{', '.join(ALLOWED_FORMATS)}`\nTo disable, use "
                   "this command again.")
            if not channel.permissions_for(interaction.guild.me).embed_links:
                msg += ("I won't be able to process logs without Embed "
                        "Links permission.")
        else:
            msg = ("Automatic EVTC processing diasbled")
        await interaction.response.send_message(msg)

    def generate_evtc_api_key(self) -> None:
        return secrets.token_urlsafe(64)

    async def get_user_evtc_api_key(self,
                                    user: discord.User) -> Union[str, None]:
        doc = await self.db.evtc.api_keys.find_one({"user": user.id}) or {}
        return doc.get("token", None)

    @evtc_automation_group.command(name="api_key")
    @app_commands.describe(operation="The operation to perform")
    @app_commands.choices(operation=[
        Choice(name="View your API key", value="view"),
        Choice(name="Generate or regenerate your API key", value="generate"),
        Choice(name="Delete your API key", value="delete")
    ])
    async def evtc_api_key(self, interaction: discord.Interaction,
                           operation: str):
        """Generate an API key for third-party apps that automatically upload EVTC logs"""
        await interaction.response.defer(ephemeral=True)
        existing_key = await self.get_user_evtc_api_key(interaction.user)
        if operation == "delete":
            if not existing_key:
                return await interaction.followup.send(
                    "You don't have an EVTC API key generated.")
            await self.db.evtc.api_keys.delete_one(
                {"_id": interaction.user.id})
            return await interaction.followup.send(
                "Your EVTC API key has been deleted.")
        if operation == "view":
            if not existing_key:
                return await interaction.followup.send(
                    "You don't have an EVTC API key generated. Use "
                    "`/evtc api_key generate` to generate one.")
            return await interaction.followup.send(
                f"Your EVTC API key is ```{existing_key}```")
        if operation == "generate":
            key = self.generate_evtc_api_key()
            await self.db.evtc.api_keys.insert_one({
                "user": interaction.user.id,
                "token": key
            })
            new = "new " if existing_key else ""
            return await interaction.followup.send(
                f"Your {new}new EVTC API key is:\n```{key}```You may use "
                "it with utilities that automatically upload logs to link "
                "them with your account, and potentially post them to "
                "certain channels. See `/evtc_automation` for more\n\nYou may "
                "revoke the key at any time with `/evtc api_key delete`, or "
                "regenerate it with `/evtc api_key generate`. Don't share "
                "this key with anyone.\nYou can also use this "
                "key without setting any upload destinations. Doing so will "
                "still append the report links to `/bosses` results")

    async def get_evtc_notification_channel(self, id, user):
        await self.db.evtc.channels.find_one({
            "channel_id": id,
            "user": user.id
        })

    @autopost_group.command(name="add_destination")
    @app_commands.checks.has_permissions(embed_links=True,
                                         use_external_emojis=True)
    @app_commands.checks.bot_has_permissions(embed_links=True,
                                             use_external_emojis=True)
    async def evtc_autoupload_add(self, interaction: discord.Interaction):
        """Add this channel as a personal destination to autopost EVTC logs to
        """
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        key = await self.get_user_evtc_api_key(interaction.user)
        if not key:
            return await interaction.followup.send(
                "You don't have an EVTC API key generated. Use "
                "`/evtc api_key generate` to generate one. Confused about "
                "what this is? The aforementioned command includes a tutorial")
        doc = await self.db.evtc.destinations.find_one(
            {
                "user_id": interaction.user.id,
                "channel_id": channel.id
            }) or {}
        if interaction.guild:
            channel_doc = await self.bot.database.get(channel, self)
            if channel_doc.get("evtc.disabled", False):
                return await interaction.followup.send(
                    "This channel is disabled for EVTC processing.")
        if doc:
            return await interaction.followup.send(
                "This channel is already a destination. If you're "
                "looking to remove it, see "
                "`/evtc_automation remove_destinations`")
        results = await self.call_api("account", interaction.user, ["account"])
        guild_ids = results.get("guilds")
        if guild_ids:
            endpoints = [f"guild/{gid}" for gid in guild_ids]
            guilds = await self.call_multiple(endpoints)
        view = EvtcGuildSelectionView(self, guilds)
        await interaction.followup.send(
            "If you wish to use this channel to post only "
            "the logs made while representing a specific guild, select "
            "them from the list below. Otherwise, click `Next`.",
            view=view,
            ephemeral=True)
        if await view.wait():
            return
        await self.db.evtc.destinations.insert_one({
            "user_id":
            interaction.user.id,
            "channel_id":
            channel.id,
            "guild_ids":
            view.selected_guilds,
            "guild_tags": [
                guild["tag"] for guild in guilds
                if guild["id"] in view.selected_guilds
            ]
        })

    @autopost_group.command(name="remove_destinations")
    async def evtc_autoupload_remove(self, interaction: discord.Interaction):
        """Remove chosen EVTC autoupload destinations"""
        await interaction.response.defer(ephemeral=True)
        destinations = await self.db.evtc.destinations.find({
            "user_id":
            interaction.user.id
        }).to_list(None)
        channels = [
            self.bot.get_channel(dest["channel_id"]) for dest in destinations
        ]
        if not channels:
            return await interaction.followup.send(
                "You don't have any autopost destinations yet.")
        view = discord.ui.View()
        view.add_item(
            EvtcAutouploadDestinationsSelect(self, channels, destinations))
        await interaction.followup.send("** **", view=view)

    async def process_evtc(self, files: list[discord.Attachment], user,
                           destination):
        embeds = []
        for attachment in files:
            if attachment.filename.endswith(ALLOWED_FORMATS):
                try:
                    resp = await self.upload_log(attachment, user)
                    data = await self.get_encounter_data(resp["id"])
                    embeds.append(await
                                  self.upload_embed(destination, data,
                                                    resp["permalink"]))
                except Exception as e:
                    self.log.exception("Exception processing EVTC log ",
                                       exc_info=e)
                    return await destination.send(
                        content="Error processing your log! :x:",
                        ephemeral=True)
        for embed in embeds:
            await destination.send(embed=embed)

    @tasks.loop(seconds=5)
    async def post_evtc_notifications(self):
        cursor = self.db.evtc.notifications.find({"posted": False})
        async for doc in cursor:
            try:
                user = self.bot.get_user(doc["user_id"])
                destinations = await self.db.evtc.destinations.find({
                    "user_id":
                    user.id
                }).to_list(None)
                for destination in destinations:
                    destination["channel"] = self.bot.get_channel(
                        destination["channel_id"])
                data = await self.get_encounter_data(doc["encounter_id"])
                recorded_by = data.get("recordedBy", None)
                recorded_player_guild = None
                for player in data["players"]:
                    if player["name"] == recorded_by:
                        recorded_player_guild = player.get("guildID")
                        break
                embed = await self.upload_embed(None, data, doc["permalink"])
                embed.set_footer(
                    text="Autoposted by "
                    f"{user.name}#{user.discriminator}({user.id})."
                    " The bot respects the user's permissions; remove their "
                    "permission to send messages or embed "
                    "links to stop these messsages.")
                for destination in destinations:
                    try:
                        channel = destination["channel"]
                        if destination[
                                "guild_ids"] and recorded_by and recorded_player_guild:
                            if destination["guild_ids"]:
                                if recorded_player_guild not in destination[
                                        "guild_ids"]:
                                    continue
                        if not channel:
                            continue
                        has_permission = False
                        if guild := channel.guild:
                            members = [
                                channel.guild.me,
                                guild.get_member(user.id)
                            ]
                            for member in members:
                                if not channel.permissions_for(
                                        member).embed_links:
                                    break
                                if not channel.permissions_for(
                                        member).send_messages:
                                    break
                                if not channel.permissions_for(
                                        member).use_external_emojis:
                                    break
                            else:
                                has_permission = True
                        else:
                            has_permission = True
                    except asyncio.TimeoutError:
                        raise
                    except Exception as e:
                        self.log.exception(
                            "Exception during evtc notificaitons", exc_info=e)
                        continue
                    if has_permission:
                        try:
                            await channel.send(embed=embed)
                        except discord.HTTPException as e:
                            self.log.exception(e)
                            continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.exception("Exception during evtc notificaitons",
                                   exc_info=e)
            finally:
                await self.db.evtc.notifications.update_one(
                    {"_id": doc["_id"]}, {"$set": {
                        "posted": True
                    }})

    @post_evtc_notifications.before_loop
    async def before_post_evtc_notifications(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.attachments:
            return
        for attachment in message.attachments:
            if attachment.filename.endswith(ALLOWED_FORMATS):
                break
        else:
            return
        autodelete = False
        if not message.guild:
            doc = await self.bot.database.get(message.channel, self)
            settings = doc.get("evtc", {})
            if not settings.get("enabled"):
                return
            autodelete = settings.get("autodelete", False)
        await self.process_evtc(message.attachments, message.author,
                                message.channel)
        if autodelete:
            try:
                if message.channel.permissions_for(
                        message.channel.me).manage_messages:
                    await message.delete()
            except discord.Forbidden:
                pass
