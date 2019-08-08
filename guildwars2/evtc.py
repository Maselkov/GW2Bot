import datetime

import aiohttp
import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError
from .utils.chat import embed_list_lines

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
                    await self.bot.database.set(
                        user, {"dpsreport_token": token}, self)
                    return token
            except:
                return None

    async def upload_log(self, file, user):
        params = {"json": 1}
        token = await self.get_dpsreport_usertoken(user)
        if token:
            params["userToken"] = token
        data = aiohttp.FormData()
        data.add_field("file", await file.read(), filename=file.filename)
        async with self.session.post(
                UPLOAD_URL, data=data, params=params) as r:
            resp = await r.json()
            error = resp["error"]
            if error:
                raise APIError(error)
            return resp

    async def upload_embed(self, ctx, result):
        if not result["encounter"]["jsonAvailable"]:
            return None
        async with self.session.get(
                JSON_URL, params={"id": result["id"]}) as r:
            data = await r.json()
        lines = []
        targets = data["phases"][0]["targets"]
        group_dps = sum(p["dpsTargets"][0][0]["dps"] for p in data["players"])

        def get_graph(percentage):
            bar_count = round(percentage / 5)
            bars = ""
            bars += "▓" * bar_count
            bars += "░" * (20 - bar_count)
            return bars

        def get_dps(player):
            bars = ""
            dps = player["dpsTargets"][0][0]["dps"]
            percentage = round(100 / group_dps * dps)
            bars = get_graph(percentage)
            bars += f"` **{dps}** DPS | **{percentage}%** of group DPS"
            return bars

        players = sorted(
            data["players"],
            key=lambda p: p["dpsTargets"][0][0]["dps"],
            reverse=True)
        for player in players:
            prof = self.get_emoji(
                ctx, player["profession"], fallback=True, fallback_fmt="{} -")
            line = f"{prof} **{player['name']}** *({player['account']})*"
            lines.append(line)
        dpses = []
        charater_name_max_length = 19
        for player in players:
            line = self.get_emoji(
                ctx, player["profession"], fallback=True, fallback_fmt="{} -")
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
        embed = discord.Embed(
            title="DPS Report",
            description="Encounter duration: " + duration,
            url=result["permalink"],
            color=color)
        boss_lines = []
        target = data["targets"][0]
        if data["success"]:
            health_left = 0
        else:
            percent_burned = target["healthPercentBurned"]
            health_left = 100 - percent_burned
        boss_lines.append(f"Health: **{health_left}%**")
        boss_lines.append(get_graph(health_left))
        embed.add_field(name="> **BOSS**", value="\n".join(boss_lines))
        embed = embed_list_lines(embed, lines, "> **PLAYERS**")
        embed = embed_list_lines(embed, dpses, "> **DPS**")
        boss = self.gamedata["bosses"].get(str(result["encounter"]["bossId"]))
        date = datetime.datetime.strptime(data["timeEnd"] + "00",
                                          "%Y-%m-%d %H:%M:%S %z")
        start_date = datetime.datetime.strptime(data["timeStart"] + "00",
                                                "%Y-%m-%d %H:%M:%S %z")
        date = date.astimezone(datetime.timezone.utc)
        start_date = start_date.astimezone(datetime.timezone.utc)
        doc = {
            "boss_id": result["encounter"]["bossId"],
            "start_date": start_date,
            "date": date,
            "players": [player["account"] for player in data["players"]],
            "permalink": result["permalink"],
            "success": data["success"],
            "duration": duration_time
        }
        await self.db.encounters.insert_one(doc)
        embed.timestamp = date
        embed.set_footer(text="Recorded at", icon_url=self.bot.user.avatar_url)
        if boss:
            embed.set_author(name=boss["name"], icon_url=boss["icon"])
        return embed

    @commands.group(case_insensitive=True)
    async def evtc(self, ctx):
        """Process an EVTC combat log or enable automatic processing

        Simply upload your file and in the "add a comment" field type $evtc,
        in other words invoke this command while uploading a file.
        Use this command ($evtc) without uploading a file to see other commands
        """
        if ctx.invoked_subcommand is None and not ctx.message.attachments:
            return await ctx.send_help(ctx.command)
        for attachment in ctx.message.attachments:
            if attachment.filename.endswith(ALLOWED_FORMATS):
                break
        else:
            return await ctx.send_help(ctx.command)
        if ctx.guild:
            doc = await self.bot.database.get(ctx.channel, self)
            settings = doc.get("evtc", {})
            enabled = settings.get("enabled")
            if not ctx.channel.permissions_for(ctx.me).embed_links:
                return await ctx.send(
                    "I need embed links permission to process logs.")
            if enabled:
                return
        await self.process_evtc(ctx.message)

    @commands.cooldown(1, 5, BucketType.guild)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @evtc.command(name="channel")
    async def evtc_channel(self, ctx):
        """Sets this channel to be automatically used to process logs"""
        doc = await self.bot.database.get(ctx.channel, self)
        enabled = not doc.get("evtc.enabled", False)
        await self.bot.database.set(ctx.channel, {"evtc.enabled": enabled},
                                    self)
        if enabled:
            msg = ("Automatic EVTC processing enabled. Simply upload the file "
                   "wish to be processed in this channel. Accepted "
                   "formats: `.evtc`, `.zevtc`, `.zip` ")
            if not ctx.channel.permissions_for(ctx.me).embed_links:
                await ctx.send("I won't be able to process logs without Embed "
                               "Links permission.")
        else:
            msg = ("Automatic EVTC processing diasbled")
        await ctx.send(msg)

    async def process_evtc(self, message):
        embeds = []
        prompt = await message.channel.send("Processing logs... " +
                                            self.get_emoji(message, "loading"))
        for attachment in message.attachments:
            if attachment.filename.endswith(ALLOWED_FORMATS):
                try:
                    resp = await self.upload_log(attachment, message.author)
                    embeds.append(await self.upload_embed(message, resp))
                except Exception as e:
                    self.log.exception(
                        "Exception processing EVTC log ", exc_info=e)
                    return await prompt.edit(
                        content="Error processing your log! :x:")
        for embed in embeds:
            await message.channel.send(embed=embed)
        try:
            await prompt.delete()
            await message.delete()
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.attachments:
            return
        if not message.guild:
            return
        for attachment in message.attachments:
            if attachment.filename.endswith(ALLOWED_FORMATS):
                break
        else:
            return
        doc = await self.bot.database.get(message.channel, self)
        settings = doc.get("evtc", {})
        enabled = settings.get("enabled")
        if not enabled:
            return
        await self.process_evtc(message)
