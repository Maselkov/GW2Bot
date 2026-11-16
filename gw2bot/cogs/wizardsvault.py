"""/wizardsvault: the account's Wizard's Vault objectives."""
import datetime

import discord
from discord import app_commands

from ..i18n import N_, Catalog
from ..utils.chat import embed_list_lines
from .base import GW2Cog

ASTRAL_ACCLAIM = 63
WEEKLY_RESET = datetime.timedelta(hours=7, minutes=30)  # Mondays, UTC


# Untranslated text, for callers that don't give a language
ENGLISH = Catalog()
# The objectives' tracks, as the API names them
TRACKS = {"PvP": N_("PvP"), "WvW": N_("WvW")}


def objective_line(objective, t=ENGLISH.t, lang="en"):
    """One objective with its state: claimed, ready to claim, or progress.
    Its title is in the language the API was asked for."""
    title = objective["title"]
    if objective["track"] != "PvE":
        title = f"[{t(lang, TRACKS.get(objective['track'], objective['track']))}] {title}"
    current = objective["progress_current"]
    complete = objective["progress_complete"]
    if objective["claimed"]:
        line = f"✅ {title}"
    elif complete and current >= complete:
        line = f"🎁 {title} · {t(lang, N_('ready to claim'))}"
    elif complete > 1:
        line = f"▫️ {title} · {current}/{complete}"
    else:
        line = f"▫️ {title}"
    return f"{line} · {objective['acclaim']} {t(lang, ACCLAIM_SHORT)}"


# Astral Acclaim, abbreviated
ACCLAIM_SHORT = N_("AA")


def section_name(name, data, t=ENGLISH.t, lang="en"):
    """Field name with the meta progress, for the daily and weekly lists."""
    progress = f"{data['meta_progress_current']}/{data['meta_progress_complete']}"
    if data["meta_reward_claimed"]:
        reward = t(lang, N_("reward claimed"))
    else:
        reward = t(lang, N_("reward: {acclaim} {short}"), acclaim=data["meta_reward_astral"],
                   short=t(lang, ACCLAIM_SHORT))
    return f"{t(lang, name)} · {progress} · {reward}"


def next_daily_reset(now):
    return (now + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)


def next_weekly_reset(now):
    monday = (now - datetime.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    reset = monday + WEEKLY_RESET
    if reset <= now:
        reset += datetime.timedelta(weeks=1)
    return reset


class WizardsVault(GW2Cog):

    @app_commands.command(name="wizardsvault")
    async def wizards_vault(self, interaction: discord.Interaction):
        """Your Wizard's Vault objectives and their progress

        Required permissions: progression
        """
        lang = await self.lang(interaction)
        await interaction.response.defer()
        user = interaction.user
        doc = await self.fetch_key(user, ["progression"])
        endpoints = [
            "account/wizardsvault/daily",
            "account/wizardsvault/weekly",
            "account/wizardsvault/special",
        ]
        # The objectives' titles in the user's language
        daily, weekly, special = await self.call_multiple(endpoints,
                                                          key=doc["key"], lang=lang)
        now = datetime.datetime.now(datetime.timezone.utc)
        embed = discord.Embed(
            title=self.t(lang, N_("Wizard's Vault")),
            description=self.t(
                lang, N_("Daily reset {daily} · Weekly reset {weekly}"),
                daily=f"<t:{int(next_daily_reset(now).timestamp())}:R>",
                weekly=f"<t:{int(next_weekly_reset(now).timestamp())}:R>"),
            color=await self.get_embed_color(interaction))
        for name, data in (N_("Daily"), daily), (N_("Weekly"), weekly):
            if data["objectives"]:
                embed_list_lines(embed,
                                 [objective_line(o, self.t, lang) for o in data["objectives"]],
                                 section_name(name, data, self.t, lang))
        if special["objectives"]:
            embed_list_lines(embed,
                             [objective_line(o, self.t, lang) for o in special["objectives"]],
                             self.t(lang, N_("Special")))
        if "wallet" in doc["permissions"]:
            wallet = await self.call_api("account/wallet", key=doc["key"])
            acclaim = next(
                (c["value"] for c in wallet if c["id"] == ASTRAL_ACCLAIM), 0)
            embed.add_field(name=self.t(lang, N_("Astral Acclaim")), value=acclaim)
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        embed.set_footer(text=self.t(lang, N_("{short} = {name}"), short=self.t(lang, ACCLAIM_SHORT),
                                     name=self.t(lang, N_("Astral Acclaim"))),
                         icon_url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(WizardsVault(bot))
