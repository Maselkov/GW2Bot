import asyncio
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .exceptions import APIError


class AchievementsMixin:
    @commands.command()
    @commands.cooldown(1, 3, BucketType.user)
    async def achievementinfo(self, ctx, *, achievement):
        """Display achievement information and your completion status"""
        user = ctx.author
        ach_sanitized = re.escape(achievement)
        search = re.compile(ach_sanitized + ".*", re.IGNORECASE)
        cursor = self.db.achievements.find({"name": search})
        number = await cursor.count()
        if not number:
            return await ctx.send(
                "Your search gave me no results, sorry. Check for typos.")
        if number > 20:
            return await ctx.send(
                "Your search gave me {} results. Please be more specific".
                format(number))
        items = []
        msg = "Which one of these interests you? Type it's number```"
        async for item in cursor:
            items.append(item)
        if number != 1:
            for c, m in enumerate(items):
                msg += "\n{}: {}".format(c, m["name"])
            msg += "```"
            message = await ctx.send(msg)

            def check(m):
                return m.channel == ctx.channel and m.author == user

            try:
                answer = await self.bot.wait_for(
                    "message", timeout=120, check=check)
            except asyncio.TimeoutError:
                return message.edit(content="No response in time")
            try:
                num = int(answer.content)
                choice = items[num]
            except:
                return await message.edit(
                    content="That's not a number in the list")
            try:
                await message.delete()
                await answer.delete()
            except:
                pass
        else:
            choice = items[0]
        try:
            endpoint = "account/achievements?id=" + str(choice["_id"])
            results = await self.call_api(endpoint, user, ["progression"])
        except APIError as e:
            return await self.error_handler(ctx, e)
        embed = await self.ach_embed(results, choice)
        try:
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("Need permission to embed links")

    async def ach_embed(self, res, ach):
        description = ach["description"]
        data = discord.Embed(
            title=ach["name"], description=description, color=self.embed_color)
        if "icon" in ach:
            data.set_thumbnail(url=ach["icon"])
        data.add_field(name="Requirement", value=ach["requirement"])
        tiers = ach["tiers"]
        repeated = res["repeated"] if "repeated" in res else 0
        max_prog = len(tiers)
        max_ap = self.max_ap(ach, repeated)
        earned_ap = self.earned_ap(ach, res)
        tier_prog = self.tier_progress(tiers, res)
        progress = "Completed" if max_prog == tier_prog else "{}/{}".format(
            tier_prog, max_prog)
        if "Repeatable" in ach["flags"]:
            progress += "\nRepeats: {}".format(repeated)
        data.add_field(name="Progress", value=progress, inline=False)
        data.add_field(
            name="AP earned",
            value="{}/{}".format(earned_ap, max_ap),
            inline=False)
        return data

    def tier_progress(self, tiers, res):
        progress = 0
        for tier in tiers:
            if res["current"] >= tier["count"]:
                progress += 1
        return progress

    def max_ap(self, ach, repeatable=False):
        if repeatable:
            return ach["point_cap"]
        return sum([t["points"] for t in ach["tiers"]])

    def earned_ap(self, ach, res):
        earned = 0
        repeats = res["repeated"] if "repeated" in res else 0
        max_possible = self.max_ap(ach, repeats)
        for tier in ach["tiers"]:
            if res["current"] >= tier["count"]:
                earned += tier["points"]
        earned += self.max_ap(ach) * repeats
        if earned > max_possible:
            earned = max_possible
        return earned

    async def total_possible_ap(self):
        cursor = self.db.achievements.find()
        total = 15000
        async for ach in cursor:
            if "Repeatable" in ach["flags"]:
                total += ach["point_cap"]
            else:
                for tier in ach["tiers"]:
                    total += tier["points"]
        return total

    async def calculate_user_ap(self, res, acc_res):
        total = acc_res["daily_ap"] + acc_res["monthly_ap"]
        for ach in res:
            doc = await self.db.achievements.find_one({"_id": ach["id"]})
            total += self.earned_ap(doc, ach)
        return total
