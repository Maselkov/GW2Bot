import asyncio
import datetime
import secrets
from typing import Union

import aiohttp
import discord
from discord.ext import commands, tasks
from discord_slash import MenuContext, cog_ext
from discord_slash.model import (ButtonStyle, ContextMenuType,
                                 SlashCommandOptionType)
from discord_slash.utils.manage_components import (create_actionrow,
                                                   create_button,
                                                   create_select,
                                                   create_select_option,
                                                   wait_for_component)

from .exceptions import APIError
from .utils.chat import (embed_list_lines, en_space, magic_space,
                         zero_width_space)

UTC_TZ = datetime.timezone.utc

BASE_URL = "https://dps.report/"
UPLOAD_URL = BASE_URL + "uploadContent"
JSON_URL = BASE_URL + "getJson"
TOKEN_URL = BASE_URL + "getUserToken"
ALLOWED_FORMATS = (".evtc", ".zevtc", ".zip")


class EvtcMixin:
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

    async def upload_embed(self, ctx, data, permalink):
        lines = []
        force_emoji = False if ctx else True
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
            prof = self.get_emoji(ctx,
                                  player["profession"],
                                  force_emoji=force_emoji)
            line = f"{prof} **{player['name']}** *({player['account']})*"
            if down_count:
                line += (
                    f" | {self.get_emoji(ctx, 'downed', force_emoji=force_emoji)}Downed "
                    f"count: **{down_count}**")
            lines.append(line)
        dpses = []
        charater_name_max_length = 19
        for player in players:
            line = self.get_emoji(ctx,
                                  player["profession"],
                                  force_emoji=force_emoji,
                                  fallback=True,
                                  fallback_fmt="")
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
        blank = self.get_emoji(ctx, "blank", force_emoji=force_emoji)
        first = True
        for buff in sought_buffs:
            if first and not blank:
                icon_line = icon_line[:-2]
            if not first:
                if blank:
                    icon_line += blank + blank
                else:
                    icon_line += separator + (en_space * 4)
            icon_line += self.get_emoji(ctx,
                                        buff,
                                        fallback=True,
                                        fallback_fmt="{:1.1}",
                                        force_emoji=force_emoji)
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
            line = self.get_emoji(ctx,
                                  player["profession"],
                                  force_emoji=force_emoji,
                                  fallback=True,
                                  fallback_fmt="")
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
        embed.set_footer(text="Recorded at", icon_url=self.bot.user.avatar_url)
        if boss:
            embed.set_author(name=data["fightName"], icon_url=boss["icon"])
        return embed

    @cog_ext.cog_context_menu(target=ContextMenuType.MESSAGE,
                              name="ProcessEVTC")
    async def evtc(self, ctx: MenuContext):
        """Process an EVTC combat log in an attachment"""
        message = ctx.target_message
        if not message.attachments:
            return await ctx.send(
                "The message must have an attached evtc file!", hidden=True)
        for attachment in message.attachments:
            if attachment.filename.endswith(ALLOWED_FORMATS):
                break
        else:
            return await ctx.send(
                "The attachment seems not to be of a correct filetype.\n"
                f"Allowed file extensions: `{', '.join(ALLOWED_FORMATS)}`",
                hidden=True)
        if ctx.guild:
            if not ctx.channel.permissions_for(ctx.me).embed_links:
                return await ctx.send(
                    "I need embed links permission to process logs.",
                    hidden=True)
        await ctx.defer()
        await self.process_evtc(message, ctx)

    @cog_ext.cog_subcommand(
        base="evtc",
        name="channel",
        base_description="EVTC related commands",
        options=[{
            "name": "channel",
            "description":
            "The channel to enable automatic EVTC processing on.",
            "type": SlashCommandOptionType.CHANNEL,
            "required": True,
            "channel_types": [0]
        }, {
            "name": "autodelete",
            "description":
            "Automatically delete message after processing the EVTC log",
            "type": SlashCommandOptionType.BOOLEAN,
            "required": True
        }])
    async def evtc_channel(self, ctx, channel: discord.TextChannel,
                           autodelete):
        """Sets this channel to be automatically used to process EVTC logs"""
        if not ctx.guild:
            return await ctx.send("This command can only be used in a server.",
                                  hidden=True)
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(
                "You need the manage server permission to use this command.",
                hidden=True)
        doc = await self.bot.database.get(ctx.channel, self)
        enabled = not doc.get("evtc.enabled", False)
        await self.bot.database.set(ctx.channel, {
            "evtc.enabled": enabled,
            "evtc.autodelete": autodelete
        }, self)
        if enabled:
            msg = ("Automatic EVTC processing enabled. Simply upload the file "
                   f"wish to be processed in {channel.mention}, while "
                   "@mentioning the bot in the same message.. Accepted "
                   f"formats: `{', '.join(ALLOWED_FORMATS)}`\nTo disable, use "
                   "this command again.")
            if not channel.permissions_for(ctx.me).embed_links:
                msg += ("I won't be able to process logs without Embed "
                        "Links permission.")
        else:
            msg = ("Automatic EVTC processing diasbled")
        await ctx.send(msg)

    def generate_evtc_api_key(self) -> None:
        return secrets.token_urlsafe(64)

    async def get_user_evtc_api_key(self,
                                    user: discord.User) -> Union[str, None]:
        doc = await self.db.evtc.api_keys.find_one({"user": user.id}) or {}
        return doc.get("token", None)

    @cog_ext.cog_subcommand(base="evtc",
                            name="api_key",
                            base_description="EVTC related commands",
                            options=[{
                                "name":
                                "operation",
                                "description":
                                "The operaiton to perform.",
                                "type":
                                SlashCommandOptionType.STRING,
                                "required":
                                True,
                                "choices": [{
                                    "value": "view",
                                    "name": "View your API key."
                                }, {
                                    "value":
                                    "generate",
                                    "name":
                                    "Generate or regenerate your API key."
                                }, {
                                    "value": "delete",
                                    "name": "Delete your API key."
                                }]
                            }])
    async def evtc_api_key(self, ctx, operation):
        """Generate an API key for third-party apps that automatically upload EVTC logs"""
        await ctx.defer(hidden=True)
        existing_key = await self.get_user_evtc_api_key(ctx.author)
        if operation == "delete":
            if not existing_key:
                return await ctx.send(
                    "You don't have an EVTC API key generated.")
            await self.db.evtc.api_keys.delete_one({"_id": ctx.author.id})
            return await ctx.send("Your EVTC API key has been deleted.")
        if operation == "view":
            if not existing_key:
                return await ctx.send(
                    "You don't have an EVTC API key generated. Use "
                    "`/evtc api_key generate` to generate one.")
            return await ctx.send(f"Your EVTC API key is ```{existing_key}```")
        if operation == "generate":
            key = self.generate_evtc_api_key()
            await self.db.evtc.api_keys.insert_one({
                "user": ctx.author.id,
                "token": key
            })
            new = "new " if existing_key else ""
            return await ctx.send(
                f"Your {new}new EVTC API key is:\n```{key}```You may use "
                "it with utilities that automatically upload logs to link "
                "them with your account, and potentially post them to "
                "certain channels. See `/evtc autopost` for more\n\nYou may "
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

    @cog_ext.cog_subcommand(
        base="evtc",
        subcommand_group="autopost",
        sub_group_desc="Automatically post processed EVTC logs uploaded by "
        "third party utilities",
        name="add_destination",
        base_description="EVTC related commands",
    )
    async def evtc_autoupload_add(self, ctx):
        """Add this channel as a destination to autopost EVTC logs too"""
        await ctx.defer(hidden=True)
        channel = self.bot.get_channel(ctx.channel_id)
        key = await self.get_user_evtc_api_key(ctx.author)
        if not key:
            return await ctx.send(
                "You don't have an EVTC API key generated. Use "
                "`/evtc api_key generate` to generate one. Confused about "
                "what this is? The aforementioned command includes a tutorial")
        doc = await self.db.evtc.destinations.find_one({
            "user_id": ctx.author.id,
            "channel_id": channel.id
        }) or {}
        if ctx.guild:
            channel_doc = await self.bot.database.get(ctx.channel, self)
            if channel_doc.get("evtc.disabled", False):
                return await ctx.send(
                    "This channel is disabled for EVTC processing.")
            members = [channel.guild.me, ctx.author]
            for member in members:
                if not channel.permissions_for(member).embed_links:
                    return await ctx.send(
                        "Make sure that both the bot and you have "
                        "Embed Links permission in this channel.")
                if not channel.permissions_for(member).send_messages:
                    return await ctx.send(
                        "Make sure that both the bot and you have "
                        "Send Messages permission in this channel.")
                if not channel.permissions_for(member).use_external_emojis:
                    return await ctx.send(
                        "Make sure that both the bot and you have "
                        "Use External Emojis permission in this channel.")
        if doc:
            return await ctx.send(
                "This channel is already a destination. If you're "
                "looking to remove it, see "
                "`/evtc autopost remove_destinations`")
        try:
            results = await self.call_api("account", ctx.author, ["account"])
            # TODO test guilds
        except APIError as e:
            return await self.error_handler(ctx, e)
        guild_ids = results.get("guilds")
        if guild_ids:
            endpoints = [f"guild/{gid}" for gid in guild_ids]
            try:
                guilds = await self.call_multiple(endpoints)
            except APIError as e:
                return await self.error_handler(ctx, e)
        options = []
        for guild in guilds:
            name = f"{guild['name']} [{guild['tag']}]"
            options.append(create_select_option(name, value=guild["id"]))
        select = create_select(min_values=1,
                               max_values=len(options),
                               options=options,
                               placeholder="Select guilds.")
        button = create_button(style=ButtonStyle.blue,
                               emoji="➡️",
                               label="Next",
                               custom_id="next")
        components = [create_actionrow(button), create_actionrow(select)]
        msg = await ctx.send(
            "If you wish to use this channel to post only "
            "the logs made while representing a specific guild, select "
            "them from the list below. Otherwise, click `Next`.",
            components=components,
            hidden=True)
        try:
            answer = await wait_for_component(self.bot,
                                              components=components,
                                              timeout=120)
            await answer.defer()
            selected_guilds = answer.selected_options or []
        except asyncio.TimeoutError:
            return await msg.edit(content="Timed out.", components=None)
        await self.db.evtc.destinations.insert_one({
            "user_id":
            ctx.author.id,
            "channel_id":
            channel.id,
            "guild_ids":
            selected_guilds,
            "guild_tags": [
                guild["tag"] for guild in guilds
                if guild["id"] in selected_guilds
            ]
        })
        await answer.edit_origin(
            content="This channel is now a destination for EVTC logs. "
            "Logs uploaded using third-party utilities with your GW2Bot "
            "EVTC API key will be posted here. You can have multiple "
            "destinations at the same time. DMs also work.\nYou can always "
            "remove it using `/evtc autopost remove_destinations`",
            components=None)

    @cog_ext.cog_subcommand(
        base="evtc",
        subcommand_group="autopost",
        sub_group_desc="Automatically post processed EVTC logs uploaded by "
        "third party utilities",
        name="remove_destinations",
        base_description="EVTC related commands",
    )
    async def evtc_autoupload_remove(self, ctx):
        """Remove EVTC autoupload destinations from a list"""
        await ctx.defer(hidden=True)
        destinations = await self.db.evtc.destinations.find({
            "user_id":
            ctx.author.id
        }).to_list(None)
        channels = [
            self.bot.get_channel(dest["channel_id"]) for dest in destinations
        ]
        if not channels:
            return await ctx.send(
                "You don't have any autopost destinations yet.")
        options = []
        for i, channel in enumerate(channels):
            # if dm channel
            if isinstance(channel, discord.DMChannel):
                name = "DM"
            else:
                if not channel:
                    name = "Inaccessible Channel"
                name = f"{channel.guild.name} - {channel.name}"
            options.append(create_select_option(name, value=str(i)))
        select = create_select(
            min_values=1,
            max_values=len(options),
            options=options,
            placeholder="Select the destinations that you want removed")
        components = [create_actionrow(select)]
        msg = await ctx.send("** **", components=components)
        try:
            answer = await wait_for_component(self.bot,
                                              components=components,
                                              timeout=120)
            choices = [destinations[int(i)] for i in answer.selected_options]
        except asyncio.TimeoutError:
            return await msg.edit(content="Timed out.", components=None)
        for choice in choices:
            await self.db.evtc.destinations.delete_one({"_id": choice["_id"]})
        await answer.edit_origin(content="Removed selected destinations.",
                                 components=None)

    async def process_evtc(self, message, ctx):
        embeds = []
        destination = ctx or message.channel
        for attachment in message.attachments:
            if attachment.filename.endswith(ALLOWED_FORMATS):
                try:
                    resp = await self.upload_log(attachment, message.author)
                    data = await self.get_encounter_data(resp["id"])
                    embeds.append(await
                                  self.upload_embed(message, data,
                                                    resp["permalink"]))
                except Exception as e:
                    self.log.exception("Exception processing EVTC log ",
                                       exc_info=e)
                    return await destination.send(
                        content="Error processing your log! :x:", hidden=True)
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
    async def on_message(self, message):
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
        await self.process_evtc(message, None)
        if autodelete:
            try:
                if message.channel.permissions_for(
                        message.channel.me).manage_messages:
                    await message.delete()
            except discord.Forbidden:
                pass
