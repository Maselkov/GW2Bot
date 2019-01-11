import math
import re

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from .utils.chat import cleanup_xml_tags, embed_list_lines
from .utils.db import prepare_search


class SkillsMixin:
    @commands.command(name="skill", aliases=["skillinfo"])
    @commands.cooldown(1, 5, BucketType.user)
    async def skillinfo(self, ctx, *, skill):
        """Information about a given skill"""
        if not skill:
            return await self.send_cmd_help(ctx)
        query = {"name": prepare_search(skill), "professions": {"$ne": None}}
        count = await self.db.skills.count_documents(query)
        cursor = self.db.skills.find(query)

        def remove_duplicates(items):
            unique_items = []
            for item in items:
                for unique in unique_items:
                    if (unique["name"] == item["name"]
                            and unique["facts"] == item["facts"]):
                        unique_items.remove(unique)
                unique_items.append(item)
            return unique_items

        choice = await self.selection_menu(
            ctx, cursor, count, filter_callable=remove_duplicates)
        if not choice:
            return
        data = await self.skill_embed(choice, ctx)
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    @commands.command(name="trait", aliases=["traitinfo"])
    @commands.cooldown(1, 5, BucketType.user)
    async def traitinfo(self, ctx, *, trait):
        """Information about a given trait"""
        if not trait:
            return await self.send_cmd_help(ctx)
        query = {
            "name": prepare_search(trait),
        }
        count = await self.db.traits.count_documents(query)
        cursor = self.db.traits.find(query)

        choice = await self.selection_menu(ctx, cursor, count)
        if not choice:
            return
        data = await self.skill_embed(choice, ctx)
        try:
            await ctx.send(embed=data)
        except discord.HTTPException:
            await ctx.send("Need permission to embed links")

    async def skill_embed(self, skill, ctx):
        def get_skill_type():
            slot = skill["slot"]
            if slot.startswith("Weapon"):
                weapon = skill["weapon_type"]
                return " {} skill {}".format(weapon, slot[-1])
            if slot.startswith("Utility"):
                return " Utility Skill"
            if slot.startswith("Profession"):
                return " Profession Skill {}".format(slot[-1])
            if slot.startswith("Pet"):
                return " Pet skill"
            if slot.startswith("Downed"):
                return " Downed skill {}".format(slot[-1])
            return " Utility Skill"

        def find_closest_emoji(field):
            best_match = ""
            field = field.replace(" ", "_").lower()
            for emoji in self.emojis:
                if emoji in field:
                    if len(emoji) > len(best_match):
                        best_match = emoji
            if best_match:
                return self.get_emoji(ctx, best_match)
            if ctx.channel.permissions_for(ctx.me).external_emojis:
                return "❔"
            return ""

        def get_resource_name(prof):
            resource = None
            if "initiative" in skill:
                resource = "Initiative"
                value = skill["initiative"]
            elif "cost" in skill:
                if prof == "Warrior":
                    resource = "Adrenaline"
                if prof == "Revenant":
                    resource = "Energy"
                if prof == "Ranger":
                    resource = "Astral Force"
                value = skill["cost"]
            if resource:
                return {
                    "text": resource + " cost",
                    "value": value,
                    "type": "ResourceCost"
                }
            return None

        replacement_attrs = [("BoonDuration", "Concentration"),
                             ("ConditionDuration", "Expertise"),
                             ("ConditionDamage",
                              "Condition Damage"), ("CritDamage", "Ferocity")]
        description = None
        if "description" in skill:
            description = cleanup_xml_tags(skill["description"])
            for tup in replacement_attrs:
                description = re.sub(*tup, description)
        url = "https://wiki.guildwars2.com/wiki/" + skill["name"].replace(
            ' ', '_')
        async with self.session.head(url) as r:
            if not r.status == 200:
                url = None
        data = discord.Embed(
            title=skill["name"],
            description=description,
            url=url,
            color=await self.get_embed_color(ctx))
        if "icon" in skill:
            data.set_thumbnail(url=skill["icon"])
        professions = skill.get("professions")
        resource = None
        if professions:
            if len(professions) == 1:
                prof = professions[0]
                resource = get_resource_name(prof)
                data.colour = discord.Color(
                    int(self.gamedata["professions"][prof.lower()]["color"],
                        16))
                data.set_footer(
                    text=prof + get_skill_type(),
                    icon_url=self.get_profession_icon(prof))
        if "facts" in skill:
            if resource:
                skill["facts"].append(resource)
            facts = self.get_skill_fields(skill)
            lines = []
            for fact in facts:
                line = ""
                if fact.get("prefix"):
                    line += "{}{}".format(
                        find_closest_emoji(fact["prefix"]), fact["prefix"])
                line += "{}{}".format(
                    find_closest_emoji(fact["field"]), fact["field"])
                if fact.get("value"):
                    line += ": " + fact["value"]
                for tup in replacement_attrs:
                    line = re.sub(*tup, line)
                lines.append(line)
            data = embed_list_lines(data, lines, "Tooltip")
        return data

    def get_skill_fields(self, skill):
        def calculate_damage(fact):
            weapon = skill.get("weapon_type")
            default = 690.5
            base_damage = None
            if weapon:
                weapon = weapon.lower()
                damage_groups = {
                    952.5: [
                        "axe", "dagger", "mace", "pistol", "scepter", "spear",
                        "trident", "speargun", "aquatic", "shortbow", "sword"
                    ],
                    857.5: ["focus", "shield", "torch"],
                    857: ["warhorn"],
                    1047.5: ["greatsword"],
                    1048: ["staff", "hammer"],
                    1000: ["longbow"],
                    1095.5: ["rifle"]
                }
                for group, weapons in damage_groups.items():
                    if weapon in weapons:
                        base_damage = group
                        break
            if not base_damage:
                base_damage = default
            hits = fact["hit_count"]
            multiplier = fact["dmg_multiplier"]
            return math.ceil(
                hits * round(base_damage * 1000 * multiplier / 2597))

        fields = []
        order = [
            "Recharge", "ResourceCost", "Damage", "Percent", "AttributeAdjust",
            "BuffConversion", "Buff", "PrefixedBuff", "Number", "Radius",
            "Duration", "Time", "Distance", "ComboField", "Heal",
            "HealingAdjust", "NoData", "Unblockable", "Range", "ComboFinisher",
            "StunBreak"
        ]
        for fact in sorted(
                skill["facts"], key=lambda x: order.index(x["type"])):
            fact_type = fact["type"]
            text = fact.get("text", "")
            if fact_type == "Recharge":
                fields.append({
                    "field": text,
                    "value": "{}s".format(fact["value"])
                })
                continue
            if fact_type == "ResourceCost":
                fields.append({"field": text, "value": str(fact["value"])})
                continue
            if fact_type == "BuffConversion":
                fields.append({
                    "field":
                    "Gain {} based on a Percentage of {}".format(
                        fact["target"], fact["source"]),
                    "value":
                    "{}%".format(fact["percent"])
                })
            if fact_type == "Damage":
                damage = calculate_damage(fact)
                value = "{} ({})".format(
                    damage, round(fact["dmg_multiplier"] * fact["hit_count"],
                                  2))
                count = fact["hit_count"]
                if count > 1:
                    text += " ({}x)".format(count)
                fields.append({"field": text, "value": value})
                continue
            if fact_type == "AttributeAdjust":
                if not text:
                    text = fact.get("target", "")
                fields.append({
                    "field": text,
                    "value": "{:,}".format(fact["value"])
                })
                continue
            if fact_type == "PrefixedBuff":
                count = fact.get("apply_count")
                status = fact.get("status", "")
                duration = fact.get("duration")
                field = " " + status
                if duration:
                    field += "({}s)".format(duration)
                prefix = fact["prefix"].get("status")
                if prefix:
                    prefix += " "
                if not count:
                    fields.append({
                        "field": status,
                        "value": "Condition Removed",
                        "prefix": prefix
                    })
                    continue
                fields.append({
                    "field": field,
                    "value": fact.get("description"),
                    "prefix": prefix
                })
                continue
            if fact_type == "Buff":
                count = fact.get("apply_count")
                if not count:
                    fields.append({
                        "field": "{status}".format(**fact),
                        "value": "Condition Removed"
                    })
                    continue
                fields.append({
                    "field":
                    "{} {status}({duration}s)".format(count, **fact),
                    "value":
                    fact.get("description")
                })
                continue
            if fact_type == "Buff":
                count = fact.get("apply_count")
                if not count:
                    fields.append({
                        "field": "{status}".format(**fact),
                        "value": "Condition Removed"
                    })
                    continue
                fields.append({
                    "field":
                    "{} {status}({duration}s)".format(count, **fact),
                    "value":
                    fact["description"]
                })
                continue
            if fact_type == "Number":
                fields.append({"field": text, "value": str(fact["value"])})
                continue
            if fact_type == "Time":
                fields.append({
                    "field": text,
                    "value": "{}s".format(fact["duration"])
                })
                continue
            if fact_type in "Duration":
                fields.append({
                    "field": text,
                    "value": "{}s".format(fact["duration"])
                })
                continue
            if fact_type == "Radius":
                fields.append({
                    "field": text,
                    "value": "{:,}".format(fact["distance"])
                })
                continue
            if fact_type == "ComboField":
                fields.append({"field": text, "value": fact["field_type"]})
                continue
            if fact_type == "ComboFinisher":
                value = fact["finisher_type"]
                percent = fact["percent"]
                if not percent == 100:
                    value += " ({}%)".format(percent)
                fields.append({"field": text, "value": value})
                continue
            if fact_type == "Distance":
                fields.append({
                    "field": text,
                    "value": "{:,}".format(fact["distance"])
                })
                continue
            if fact_type in ("Heal", "HealingAdjust"):
                fields.append({"field": text, "value": str(fact["hit_count"])})
                continue
            if fact_type == "NoData":
                fields.append({
                    "field": text,
                })
                continue
            if fact_type == "Unblockable":
                fields.append({"field": "Unblockable"})
                continue
            if fact_type == "StunBreak":
                fields.append({"field": "Breaks stun"})
                continue
            if fact_type == "Percent":
                fields.append({
                    "field": text,
                    "value": "{}%".format(fact["percent"])
                })
                continue
            if fact_type == "Range":
                fields.append({
                    "field": text,
                    "value": "{:,}".format(fact["value"])
                })
                continue
        return fields
