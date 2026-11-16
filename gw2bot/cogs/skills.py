"""Skill and trait commands: /skill and /trait."""
import math
import re

import discord
from discord import app_commands

from gw2bot.utils.chat import cleanup_xml_tags, embed_list_lines
from gw2bot.utils.wiki import page_url, profession_icon_url

from ..gamedata import ATTRIBUTES, COMBO_FIELDS, COMBO_FINISHERS, WEAPONS
from ..i18n import DEFAULT_LANGUAGE, N_, Catalog, format_number, localized_doc
from .base import GW2Cog

# Untranslated text, for callers that don't give a language
ENGLISH = Catalog()

# Profession resources, for skills' costs
RESOURCES = {
    "Initiative": N_("Initiative"),
    "Adrenaline": N_("Adrenaline"),
    "Energy": N_("Energy"),
    "Astral Force": N_("Astral Force"),
}


async def skill_embed(cog, skill, ctx, lang=DEFAULT_LANGUAGE):
    """Embed for a cached skill or trait document, in `lang`."""
    def t(text, **fields):
        return cog.t(lang, text, **fields)

    english = skill
    skill = localized_doc(skill, lang)

    def get_skill_type():
        slot = skill["slot"]
        if slot.startswith("Weapon"):
            weapon = skill["weapon_type"]
            return " " + t(N_("{weapon} skill {slot}"), weapon=t(WEAPONS.get(weapon, weapon)), slot=slot[-1])
        if slot.startswith("Utility"):
            return " " + t(N_("Utility Skill"))
        if slot.startswith("Profession"):
            return " " + t(N_("Profession Skill {slot}"), slot=slot[-1])
        if slot.startswith("Pet"):
            return " " + t(N_("Pet skill"))
        if slot.startswith("Downed"):
            return " " + t(N_("Downed skill {slot}"), slot=slot[-1])
        return " " + t(N_("Utility Skill"))

    def find_closest_emoji(field):
        best_match = ""
        field = field.replace(" ", "_").lower()
        for emoji in cog.emojis:
            if emoji in field:
                if len(emoji) > len(best_match):
                    best_match = emoji
        if best_match:
            return cog.get_emoji(ctx, best_match)
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
                "text": t(N_("{resource} cost"), resource=t(RESOURCES[resource])),
                "value": value,
                "type": "ResourceCost",
            }
        return None

    # The API's text sometimes has attribute codes instead of names
    replacement_attrs = [
        (code, t(ATTRIBUTES[code]))
        for code in ("BoonDuration", "ConditionDuration", "ConditionDamage", "CritDamage")
    ]
    description = None
    if "description" in skill:
        description = cleanup_xml_tags(skill["description"])
        for tup in replacement_attrs:
            description = re.sub(*tup, description)
    url = await page_url(cog.bot.session, skill["name"], lang, english["name"])
    data = discord.Embed(
        title=skill["name"],
        description=description,
        url=url,
        color=await cog.get_embed_color(ctx),
    )
    # TODO add profession colors and racial colors
    if "icon" in skill:
        data.set_thumbnail(url=skill["icon"])
    professions = skill.get("professions")
    resource = None
    if professions:
        if len(professions) == 1:
            prof = professions[0]
            resource = get_resource_name(prof)
            data.colour = discord.Color(
                int(cog.gamedata["professions"][prof.lower()]["color"], 16)
            )
            data.set_footer(
                # The professions' names are translated for /pvp's choices
                text=t(prof) + get_skill_type(),
                icon_url=profession_icon_url(prof),
            )
    if "facts" in skill:
        english = dict(english, facts=list(english["facts"]))
        if resource:
            skill["facts"].append(resource)
            english["facts"].append(resource)
        facts = skill_fields(skill, cog.t, lang)
        # Emojis are registered by English name; facts are in the same order
        # in every language
        english_facts = skill_fields(english)
        lines = []
        for fact, english_fact in zip(facts, english_facts):
            line = ""
            if fact.get("prefix"):
                line += "{}{}".format(
                    find_closest_emoji(english_fact.get("prefix") or ""), fact["prefix"]
                )
            line += "{}{}".format(find_closest_emoji(english_fact["field"]), fact["field"])
            if fact.get("value"):
                line += ": " + fact["value"]
            for tup in replacement_attrs:
                line = re.sub(*tup, line)
            lines.append(line)
        data = embed_list_lines(data, lines, t(N_("Tooltip")))
    return data


def skill_fields(skill, t=ENGLISH.t, lang=DEFAULT_LANGUAGE):
    """The tooltip lines for a skill's facts: [{field, value, prefix}], in
    `lang` (the facts' own text is in the language of `skill`)."""

    def number(value):
        return format_number(value, lang)
    def calculate_damage(fact):
        weapon = skill.get("weapon_type")
        default = 690.5
        base_damage = None
        if weapon:
            weapon = weapon.lower()
            damage_groups = {
                952.5: [
                    "axe",
                    "dagger",
                    "mace",
                    "pistol",
                    "scepter",
                    "spear",
                    "trident",
                    "speargun",
                    "aquatic",
                    "shortbow",
                    "sword",
                ],
                857.5: ["focus", "shield", "torch"],
                857: ["warhorn"],
                1047.5: ["greatsword"],
                1048: ["staff", "hammer"],
                1000: ["longbow"],
                1095.5: ["rifle"],
            }
            for group, weapons in damage_groups.items():
                if weapon in weapons:
                    base_damage = group
                    break
        if not base_damage:
            base_damage = default
        hits = fact["hit_count"]
        multiplier = fact["dmg_multiplier"]
        return math.ceil(hits * round(base_damage * 1000 * multiplier / 2597))

    fields = []
    order = [
        "Recharge",
        "ResourceCost",
        "Damage",
        "Percent",
        "AttributeAdjust",
        "BuffConversion",
        "Buff",
        "PrefixedBuff",
        "Number",
        "Radius",
        "Duration",
        "Time",
        "Distance",
        "ComboField",
        "Heal",
        "HealingAdjust",
        "NoData",
        "Unblockable",
        "Range",
        "ComboFinisher",
        "StunBreak",
    ]
    for fact in sorted(skill["facts"], key=lambda x: order.index(x["type"])):
        fact_type = fact["type"]
        text = fact.get("text", "")
        if fact_type == "Recharge":
            fields.append({"field": text, "value": "{}s".format(fact["value"])})
            continue
        if fact_type == "ResourceCost":
            fields.append({"field": text, "value": str(fact["value"])})
            continue
        if fact_type == "BuffConversion":
            fields.append(
                {
                    "field": t(lang, N_("Gain {target} based on a Percentage of {source}"),
                               target=t(lang, ATTRIBUTES.get(fact["target"], fact["target"])),
                               source=t(lang, ATTRIBUTES.get(fact["source"], fact["source"]))),
                    "value": "{}%".format(fact["percent"]),
                }
            )
        if fact_type == "Damage":
            damage = calculate_damage(fact)
            value = "{} ({})".format(
                damage, round(fact["dmg_multiplier"] * fact["hit_count"], 2)
            )
            count = fact["hit_count"]
            if count > 1:
                text += " ({}x)".format(count)
            fields.append({"field": text, "value": value})
            continue
        if fact_type == "AttributeAdjust":
            if not text:
                text = fact.get("target", "")
            fields.append({"field": text, "value": number(fact["value"])})
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
                fields.append(
                    {
                        "field": status,
                        "value": t(lang, N_("Condition Removed")),
                        "prefix": prefix,
                    }
                )
                continue
            fields.append(
                {"field": field, "value": fact.get("description"), "prefix": prefix}
            )
            continue
        if fact_type == "Buff":
            count = fact.get("apply_count")
            if not count:
                fields.append(
                    {
                        "field": "{status}".format(**fact),
                        "value": t(lang, N_("Condition Removed")),
                    }
                )
                continue
            fields.append(
                {
                    "field": "{} {status}({duration}s)".format(count, **fact),
                    "value": fact.get("description"),
                }
            )
            continue
        if fact_type == "Number":
            fields.append({"field": text, "value": str(fact["value"])})
            continue
        if fact_type == "Time":
            fields.append({"field": text, "value": "{}s".format(fact["duration"])})
            continue
        if fact_type in "Duration":
            fields.append({"field": text, "value": "{}s".format(fact["duration"])})
            continue
        if fact_type == "Radius":
            fields.append({"field": text, "value": number(fact["distance"])})
            continue
        if fact_type == "ComboField":
            field_type = fact["field_type"]
            fields.append({"field": text, "value": t(lang, COMBO_FIELDS.get(field_type, field_type))})
            continue
        if fact_type == "ComboFinisher":
            value = t(lang, COMBO_FINISHERS.get(fact["finisher_type"], fact["finisher_type"]))
            percent = fact["percent"]
            if not percent == 100:
                value += " ({}%)".format(percent)
            fields.append({"field": text, "value": value})
            continue
        if fact_type == "Distance":
            fields.append({"field": text, "value": number(fact["distance"])})
            continue
        if fact_type in ("Heal", "HealingAdjust"):
            fields.append({"field": text, "value": str(fact["hit_count"])})
            continue
        if fact_type == "NoData":
            fields.append(
                {
                    "field": text,
                }
            )
            continue
        if fact_type == "Unblockable":
            fields.append({"field": t(lang, N_("Unblockable"))})
            continue
        if fact_type == "StunBreak":
            fields.append({"field": t(lang, N_("Breaks stun"))})
            continue
        if fact_type == "Percent":
            fields.append({"field": text, "value": "{}%".format(fact["percent"])})
            continue
        if fact_type == "Range":
            fields.append({"field": text, "value": number(fact["value"])})
            continue
    return fields


class Skills(GW2Cog):
    async def skill_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.name_choices(self.db.skills, current, await self.lang(interaction),
                                       professions={"$ne": None})

    async def trait_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.name_choices(self.db.traits, current, await self.lang(interaction))

    @app_commands.command(name="skill")
    @app_commands.describe(
        skill="The skill name to search for. " "Example: Meteor Shower."
    )
    @app_commands.autocomplete(skill=skill_autocomplete)
    async def skillinfo(self, interaction: discord.Interaction, skill: str):
        """Information about a given skill"""
        await self.send_tooltip(interaction, skill, self.skill_autocomplete, self.db.skills, "skills")

    @app_commands.command(name="trait")
    @app_commands.describe(trait="The trait name to search for. Example: Fresh Air")
    @app_commands.autocomplete(trait=trait_autocomplete)
    async def traitinfo(self, interaction: discord.Interaction, trait: str):
        """Information about a given trait"""
        await self.send_tooltip(interaction, trait, self.trait_autocomplete, self.db.traits, "traits")

    async def send_tooltip(self, interaction, value, autocomplete, collection, kind):
        """Reply with the skill or trait `value` names."""
        lang = await self.lang(interaction)
        await interaction.response.defer()
        doc_id = await self.resolve_id(interaction, value, autocomplete)
        doc = await collection.find_one({"_id": doc_id}) if doc_id is not None else None
        if not doc:
            not_found = {"skills": N_("Could not find any skills with that name."),
                         "traits": N_("Could not find any traits with that name.")}
            return await interaction.followup.send(self.t(lang, not_found[kind]))
        data = await skill_embed(self, doc, interaction, lang)
        await interaction.followup.send(embed=data)


async def setup(bot):
    await bot.add_cog(Skills(bot))
