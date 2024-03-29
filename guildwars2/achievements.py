import math

import discord
from discord import app_commands

from .exceptions import APIError, APINotFound
from .utils.chat import cleanup_xml_tags
from .utils.db import prepare_search


class AchievementsMixin:

    async def achievement_autocomplete(self, interaction: discord.Interaction,
                                       current: str):
        if not current:
            return []
        query = {"name": prepare_search(current)}
        cursor = self.db.achievements.find(query).limit(25)
        return [
            app_commands.Choice(name=ach["name"], value=str(ach["_id"]))
            async for ach in cursor
        ]

    @app_commands.command(name="achievement")
    @app_commands.describe(
        achievement_name="Name of achievement. Example: Playing Chicken")
    @app_commands.autocomplete(achievement_name=achievement_autocomplete)
    async def achievementinfo(self, interaction: discord.Interaction,
                              achievement_name: str):
        """Display achievement information and your completion status"""
        user = interaction.user
        await interaction.response.defer()
        choice = await self.db.achievements.find_one(
            {"_id": int(achievement_name)})
        try:
            doc = await self.fetch_key(user, ["progression"])
            endpoint = "account/achievements?id=" + achievement_name
            results = await self.call_api(endpoint, key=doc["key"])
        except APINotFound:
            results = {}
        except APIError:
            raise
        embed = await self.ach_embed(interaction, results, choice)
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    async def ach_embed(self, ctx, res, ach):
        description = cleanup_xml_tags(ach["description"])
        data = discord.Embed(title=ach["name"],
                             description=description,
                             color=await self.get_embed_color(ctx))
        if "icon" in ach:
            data.set_thumbnail(url=ach["icon"])
        requirement = ach.get("requirement")
        if requirement:
            data.add_field(name="Requirement",
                           value=ach["requirement"],
                           inline=False)
        tiers = ach["tiers"]
        repeated = res["repeated"] if "repeated" in res else 0
        max_prog = len(tiers)
        max_ap = self.max_ap(ach, repeated)
        earned_ap = self.earned_ap(ach, res)
        tier_prog = self.tier_progress(tiers, res)
        completed = max_prog == tier_prog
        progress = "Completed" if completed else "{}/{}".format(
            tier_prog, max_prog)
        if "Repeatable" in ach["flags"]:
            progress += "\nRepeats: {}".format(repeated)
        footer = self.bot.user.name
        if "bits" in ach:
            lines = []
            completed_bits = res.get("bits", [])
            for i, bit in enumerate(ach["bits"]):
                if bit["type"] == "Text":
                    text = bit["text"]
                elif bit["type"] == "Item":
                    doc = await self.fetch_item(bit["id"])
                    text = doc["name"]
                elif bit["type"] == "Minipet":
                    doc = await self.db.minis.find_one({"_id": bit["id"]})
                    text = doc["name"]
                elif bit["type"] == "Skin":
                    doc = await self.db.skins.find_one({"_id": bit["id"]})
                    text = doc["name"]
                prefix = "+✔" if completed or i in completed_bits else "-✖"
                lines.append(prefix + text)
            number_of_fields = math.ceil(len(lines) / 10)
            if number_of_fields < 15:
                footer += " | Green (+) means completed. Red (-) means not"
                for i in range(number_of_fields):
                    value = "\n".join(lines[i * 10:i * 10 + 10])
                    data.add_field(name="Objectives ({}/{})".format(
                        i + 1, number_of_fields),
                                   value="```diff\n{}\n```".format(value))
        if "rewards" in ach:
            lines = []
            for rew in ach["rewards"]:
                if rew["type"] == "Coins":
                    reward = self.gold_to_coins(ctx, rew["count"])
                elif rew["type"] == "Item":
                    doc = await self.fetch_item(rew["id"])
                    cnt = str(rew["count"]) + " " if rew["count"] > 1 else ""
                    reward = cnt + doc["name"]
                elif rew["type"] == "Mastery":
                    reward = rew["region"] + " Mastery Point"
                elif rew["type"] == "Title":
                    reward = await self.get_title(rew["id"])
                    reward = "Title: " + reward
                lines.append(reward)
            data.add_field(name="Rewards",
                           value="\n".join(lines),
                           inline=False)
        data.add_field(name="Tier completion", value=progress, inline=False)
        data.add_field(name="AP earned",
                       value="{}/{}".format(earned_ap, max_ap),
                       inline=False)
        footer += f" | ID: {ach['_id']}"
        data.set_footer(text=footer, icon_url=self.bot.user.display_avatar.url)
        return data

    def tier_progress(self, tiers, res):
        progress = 0
        if not res:
            return progress
        for tier in tiers:
            if res["current"] >= tier["count"]:
                progress += 1
        return progress

    def max_ap(self, ach, repeatable=False):
        if ach is None:
            return 0
        if repeatable:
            return ach["point_cap"]
        return sum([t["points"] for t in ach["tiers"]])

    def earned_ap(self, ach, res):
        earned = 0
        if not res:
            return earned
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
            if doc is not None:
                total += self.earned_ap(doc, ach)
        return total
