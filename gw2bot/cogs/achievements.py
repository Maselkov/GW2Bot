"""/achievement, and the achievement point maths /account uses too."""
import math

import discord
from discord import app_commands

from ..gw2api.errors import APINotFound
from ..i18n import N_, localized, localized_doc
from ..utils.chat import cleanup_xml_tags
from .base import GW2Cog

# Daily and monthly achievement points aren't in /v2/achievements
DAILY_AND_MONTHLY_AP = 15000


def tier_progress(tiers, res):
    """How many tiers the progress `res` (from /v2/account/achievements)
    has completed."""
    progress = 0
    if not res:
        return progress
    for tier in tiers:
        if res["current"] >= tier["count"]:
            progress += 1
    return progress


def max_ap(ach, repeatable=False):
    """Points an achievement gives: its tiers' points, or its point cap if
    repeatable."""
    if ach is None:
        return 0
    if repeatable:
        return ach["point_cap"]
    return sum([t["points"] for t in ach["tiers"]])


def earned_ap(ach, res):
    """Points earned on an achievement, including repeats, up to its cap."""
    earned = 0
    if not res:
        return earned
    repeats = res["repeated"] if "repeated" in res else 0
    max_possible = max_ap(ach, repeats)
    for tier in ach["tiers"]:
        if res["current"] >= tier["count"]:
            earned += tier["points"]
    earned += max_ap(ach) * repeats
    if earned > max_possible:
        earned = max_possible
    return earned


async def total_possible_ap(achievements):
    """The most points an account can have, from the cached achievements."""
    total = DAILY_AND_MONTHLY_AP
    async for ach in achievements.find():
        if "Repeatable" in ach["flags"]:
            total += ach["point_cap"]
        else:
            for tier in ach["tiers"]:
                total += tier["points"]
    return total


async def account_ap(achievements, progress, account):
    """An account's points: daily and monthly from /v2/account, plus each
    achievement's in /v2/account/achievements `progress`."""
    total = account["daily_ap"] + account["monthly_ap"]
    for ach in progress:
        doc = await achievements.find_one({"_id": ach["id"]})
        if doc is not None:
            total += earned_ap(doc, ach)
    return total


class Achievements(GW2Cog):

    async def achievement_autocomplete(self, interaction: discord.Interaction,
                                       current: str):
        return await self.name_choices(self.db.achievements, current, await self.lang(interaction))

    @app_commands.command(name="achievement")
    @app_commands.describe(
        achievement_name="Name of achievement. Example: Playing Chicken")
    @app_commands.autocomplete(achievement_name=achievement_autocomplete)
    async def achievementinfo(self, interaction: discord.Interaction,
                              achievement_name: str):
        """Display achievement information and your completion status"""
        user = interaction.user
        lang = await self.lang(interaction)
        await interaction.response.defer()
        choice = await self.find_achievement(interaction, achievement_name)
        if not choice:
            return await interaction.followup.send(
                self.t(lang, N_("No achievement found matching `{search}`."), search=achievement_name))
        try:
            doc = await self.fetch_key(user, ["progression"])
            endpoint = "account/achievements?id={}".format(choice["_id"])
            results = await self.call_api(endpoint, key=doc["key"])
        except APINotFound:
            results = {}
        embed = await self.ach_embed(interaction, results, choice, lang)
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    async def find_achievement(self, interaction, name):
        """The cached achievement with this id (as picked from the
        autocomplete), or else the first whose name starts with `name`."""
        ach_id = await self.resolve_id(interaction, name, self.achievement_autocomplete)
        if ach_id is None:
            return None
        return await self.db.achievements.find_one({"_id": ach_id})

    async def ach_embed(self, ctx, res, ach, lang="en"):
        def t(text, **fields):
            return self.t(lang, text, **fields)

        # Its text in the language; the rest is the same in every language
        ach = localized_doc(ach, lang)
        description = cleanup_xml_tags(ach["description"])
        data = discord.Embed(title=ach["name"],
                             description=description,
                             color=await self.get_embed_color(ctx))
        if "icon" in ach:
            data.set_thumbnail(url=ach["icon"])
        requirement = ach.get("requirement")
        if requirement:
            data.add_field(name=t(N_("Requirement")),
                           value=ach["requirement"],
                           inline=False)
        tiers = ach["tiers"]
        repeated = res["repeated"] if "repeated" in res else 0
        max_prog = len(tiers)
        possible = max_ap(ach, repeated)
        earned = earned_ap(ach, res)
        tier_prog = tier_progress(tiers, res)
        completed = max_prog == tier_prog
        progress = t(N_("Completed")) if completed else "{}/{}".format(
            tier_prog, max_prog)
        if "Repeatable" in ach["flags"]:
            progress += "\n" + t(N_("Repeats: {count}"), count=repeated)
        footer = self.bot.user.name
        if "bits" in ach:
            lines = []
            completed_bits = res.get("bits", [])
            for i, bit in enumerate(ach["bits"]):
                if bit["type"] == "Text":
                    text = bit["text"]
                elif bit["type"] == "Item":
                    doc = await self.fetch_item(bit["id"])
                    text = localized(doc, lang) if doc else t(N_("Unknown item"))
                elif bit["type"] == "Minipet":
                    doc = await self.db.minis.find_one({"_id": bit["id"]})
                    text = localized(doc, lang) if doc else t(N_("Unknown miniature"))
                elif bit["type"] == "Skin":
                    doc = await self.db.skins.find_one({"_id": bit["id"]})
                    text = localized(doc, lang) if doc else t(N_("Unknown skin"))
                prefix = "+✔" if completed or i in completed_bits else "-✖"
                lines.append(prefix + text)
            number_of_fields = math.ceil(len(lines) / 10)
            if number_of_fields < 15:
                footer += " | " + t(N_("Green (+) means completed. Red (-) means not"))
                for i in range(number_of_fields):
                    value = "\n".join(lines[i * 10:i * 10 + 10])
                    data.add_field(name=t(N_("Objectives ({page}/{pages})"),
                                          page=i + 1, pages=number_of_fields),
                                   value="```diff\n{}\n```".format(value))
        if "rewards" in ach:
            lines = []
            for rew in ach["rewards"]:
                if rew["type"] == "Coins":
                    reward = self.gold_to_coins(ctx, rew["count"], lang)
                elif rew["type"] == "Item":
                    doc = await self.fetch_item(rew["id"])
                    cnt = str(rew["count"]) + " " if rew["count"] > 1 else ""
                    reward = cnt + (localized(doc, lang) if doc else t(N_("Unknown item")))
                elif rew["type"] == "Mastery":
                    # The region as the API names it (Tyria, Maguuma, Desert...)
                    reward = t(N_("{region} Mastery Point"), region=rew["region"])
                elif rew["type"] == "Title":
                    reward = await self.get_title(rew["id"], lang)
                    reward = t(N_("Title: {title}"), title=reward)
                lines.append(reward)
            data.add_field(name=t(N_("Rewards")),
                           value="\n".join(lines),
                           inline=False)
        data.add_field(name=t(N_("Tier completion")), value=progress, inline=False)
        data.add_field(name=t(N_("AP earned")),
                       value="{}/{}".format(earned, possible),
                       inline=False)
        footer += f" | ID: {ach['_id']}"
        data.set_footer(text=footer, icon_url=self.bot.user.display_avatar.url)
        return data


async def setup(bot):
    await bot.add_cog(Achievements(bot))
