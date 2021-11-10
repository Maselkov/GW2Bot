import calendar
import datetime
import re

import discord
from discord_slash import cog_ext
from discord_slash.model import SlashCommandOptionType

from .utils.chat import en_space, tab

DAILY_CATEGORIES = [
    {
        "value": "pve",
        "name": "PvE"
    },
    {
        "value": "pvp",
        "name": "PvP"
    },
    {
        "value": "wvw",
        "name": "WvW"
    },
    {
        "value": "fractals",
        "name": "Fractals"
    },
    {
        "value": "psna",
        "name": "PSNA - Pact Supply Network Agent"
    },
    {
        "value": "strikes",
        "name": "Strikes"
    },
]


class DailyMixin:
    @cog_ext.cog_slash(options=[
        {
            "name": "category",
            "description": "Daily type",
            "type": SlashCommandOptionType.STRING,
            "choices": [{
                "value": "all",
                "name": "All dailies"
            }] + DAILY_CATEGORIES,
            "required": True,
        },
        {
            "name": "tomorrow",
            "description":
            "Select this options to view tomorrow's dailies instead.",
            "type": SlashCommandOptionType.STRING,
            "choices": [{
                "value": "tomorrow",
                "name": "tomorrow"
            }],
            "required": False,
        },
    ])
    async def daily(self, ctx, *, category, tomorrow=""):
        """Show today's daily achievements"""
        tomorrow = bool(tomorrow)
        if category == "all":
            category = ["psna", "pve", "pvp", "wvw", "fractals", "strikes"]
        else:
            category = [category]
        embed = await self.daily_embed(category, ctx=ctx, tomorrow=tomorrow)
        await ctx.send(embed=embed)

    async def daily_all(self, ctx, tomorrow=""):
        """Show today's all dailies"""
        tomorrow = bool(tomorrow)
        embed = await self.daily_embed(
            ["psna", "pve", "pvp", "wvw", "strikes", "fractals"],
            ctx=ctx,
            tomorrow=tomorrow,
        )
        embed.set_thumbnail(
            url="https://wiki.guildwars2.com/images/1/14/Daily_Achievement.png"
        )
        await ctx.send(embed=embed)

    def get_year_day(self, tomorrow=True):
        date = datetime.datetime.utcnow().date()
        if tomorrow:
            date += datetime.timedelta(days=1)
        day = (date - date.replace(month=1, day=1)).days
        if day >= 59 and not calendar.isleap(date.year):
            day += 1
        return day

    async def daily_embed(self,
                          categories,
                          *,
                          doc=None,
                          ctx=None,
                          tomorrow=False):
        # All of this mess needs a rewrite at this point tbh, but I just keep
        # adding more on top of it. Oh well, it works.. for now
        if not doc:
            doc = await self.bot.database.get_cog_config(self)
        if ctx:
            color = await self.get_embed_color(ctx)
        else:
            color = self.embed_color
        embed = discord.Embed(title="Dailies", color=color)
        if tomorrow:
            embed.title += " tomorrow"
        key = "dailies" if not tomorrow else "dailies_tomorrow"
        dailies = doc["cache"][key]
        for category in categories:
            if category == "psna":
                if datetime.datetime.utcnow().hour >= 8:
                    value = "\n".join(dailies["psna_later"])
                else:
                    value = "\n".join(dailies["psna"])
            elif category == "fractals":
                fractals = self.get_fractals(dailies["fractals"],
                                             ctx,
                                             tomorrow=tomorrow)
                value = "\n".join(fractals[0])
            elif category == "strikes":
                category = "Priority Strike"
                strikes = self.get_strike(ctx, tomorrow=tomorrow)
                value = strikes
            else:
                lines = []
                for i, d in enumerate(dailies[category]):
                    # HACK handling for emojis for lws dailies. Needs rewrite
                    emoji = self.get_emoji(ctx, f"daily {category}")
                    if category == "pve":
                        if i == 5:
                            emoji = self.get_emoji(ctx, "daily lws3")
                        elif i == 6:
                            emoji = self.get_emoji(ctx, "daily lws4")
                    lines.append(emoji + d)
                value = "\n".join(lines)
            if category == "psna_later":
                category = "psna in 8 hours"
            value = re.sub(r"(?:Daily|Tier 4|PvP|WvW) ", "", value)
            if category.startswith("psna"):
                category = self.get_emoji(ctx, "daily psna") + category
            if category == "fractals":
                embed.add_field(name="> Daily Fractals",
                                value="\n".join(fractals[0]))
                embed.add_field(name="> CM Instabilities", value=fractals[2])
                embed.add_field(
                    name="> Recommended Fractals",
                    value="\n".join(fractals[1]),
                    inline=False,
                )

            else:
                embed.add_field(name=category.upper(),
                                value=value,
                                inline=False)
        if "fractals" in categories:
            embed.set_footer(
                text=self.bot.user.name +
                " | Instabilities shown only apply to the highest scale",
                icon_url=self.bot.user.avatar_url,
            )
        else:
            embed.set_footer(text=self.bot.user.name,
                             icon_url=self.bot.user.avatar_url)
        return embed

    def get_lw_dailies(self, tomorrow=False):
        LWS3_MAPS = [
            "Bloodstone Fen",
            "Ember Bay",
            "Bitterfrost Frontier",
            "Lake Doric",
            "Draconis Mons",
            "Siren's Landing",
        ]
        LWS4_MAPS = [
            "Domain of Istan",
            "Sandswept Isles",
            "Domain of Kourna",
            "Jahai Bluffs",
            "Thunderhead Peaks",
            "Dragonfall",
        ]
        day = self.get_year_day(tomorrow=tomorrow)
        index = day % (len(LWS3_MAPS))
        lines = []
        lines.append(f"Daily Living World Season 3 - {LWS3_MAPS[index]}")
        lines.append(f"Daily Living World Season 4 - {LWS4_MAPS[index]}")
        return lines

    def get_fractals(self, fractals, ctx, tomorrow=False):
        recommended_fractals = []
        daily_fractals = []
        fractals_data = self.gamedata["fractals"]
        for fractal in fractals:
            fractal_level = fractal.replace("Daily Recommended Fractal—Scale ",
                                            "")
            if re.match("[0-9]{1,3}", fractal_level):
                recommended_fractals.append(fractal_level)
            else:
                line = self.get_emoji(ctx, "daily fractal") + re.sub(
                    r"(?:Daily|Tier 4) ", "", fractal)
                try:
                    scale = self.gamedata["fractals"][fractal[13:]][-1]
                    instabilities = self.get_instabilities(scale,
                                                           ctx=ctx,
                                                           tomorrow=tomorrow)
                    if instabilities:
                        line += f"\n{instabilities}"
                except (IndexError, KeyError):
                    pass
                daily_fractals.append(line)
        for i, level in enumerate(sorted(recommended_fractals, key=int)):
            for k, v in fractals_data.items():
                if int(level) in v:
                    recommended_fractals[i] = "{}{} {}".format(
                        self.get_emoji(ctx, "daily recommended fractal"),
                        level, k)

        return (
            daily_fractals,
            recommended_fractals,
            self.get_cm_instabilities(ctx=ctx, tomorrow=tomorrow),
        )

    def get_psna(self, *, offset_days=0):
        offset = datetime.timedelta(hours=-8)
        tzone = datetime.timezone(offset)
        day = datetime.datetime.now(tzone).weekday()
        if day + offset_days > 6:
            offset_days = -6
        return self.gamedata["pact_supply"][day + offset_days]

    def get_strike(self, ctx, tomorrow=False):
        day = self.get_year_day(tomorrow=tomorrow)
        index = day % len(self.gamedata["strike_missions"])
        return (self.get_emoji(ctx, "daily strike") +
                self.gamedata["strike_missions"][index])

    def get_instabilities(self, fractal_level, *, tomorrow=False, ctx=None):
        fractal_level = str(fractal_level)
        day = self.get_year_day(tomorrow=tomorrow)
        if fractal_level not in self.instabilities["instabilities"]:
            return None
        levels = self.instabilities["instabilities"][fractal_level][day]
        names = []
        for instab in levels:
            name = self.instabilities["instability_names"][instab]
            if ctx:
                name = (en_space + tab +
                        self.get_emoji(ctx, name.replace(",", "")) + name)
            names.append(name)
        return "\n".join(names)

    def get_cm_instabilities(self, *, ctx=None, tomorrow=False):
        cm_instabs = []
        cm_fractals = "Nightmare", "Shattered Observatory", "Sunqua Peak"
        for fractal in cm_fractals:
            scale = self.gamedata["fractals"][fractal][-1]
            line = self.get_emoji(ctx, "daily fractal") + fractal
            instabilities = self.get_instabilities(scale,
                                                   ctx=ctx,
                                                   tomorrow=tomorrow)
            cm_instabs.append(line + "\n" + instabilities)
        return "\n".join(cm_instabs)
