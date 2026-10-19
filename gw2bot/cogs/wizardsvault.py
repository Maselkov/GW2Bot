"""/wizardsvault: the account's Wizard's Vault objectives."""
import datetime

import discord
from discord import app_commands

from .base import GW2Cog
from .guildwars2.utils.chat import embed_list_lines

ASTRAL_ACCLAIM = 63
WEEKLY_RESET = datetime.timedelta(hours=7, minutes=30)  # Mondays, UTC


def objective_line(objective):
    """One objective with its state: claimed, ready to claim, or progress."""
    title = objective["title"]
    if objective["track"] != "PvE":
        title = f"[{objective['track']}] {title}"
    current = objective["progress_current"]
    complete = objective["progress_complete"]
    if objective["claimed"]:
        line = f"✅ {title}"
    elif complete and current >= complete:
        line = f"🎁 {title} · ready to claim"
    elif complete > 1:
        line = f"▫️ {title} · {current}/{complete}"
    else:
        line = f"▫️ {title}"
    return f"{line} · {objective['acclaim']} AA"


def section_name(name, data):
    """Field name with the meta progress, for the daily and weekly lists."""
    progress = f"{data['meta_progress_current']}/{data['meta_progress_complete']}"
    if data["meta_reward_claimed"]:
        reward = "reward claimed"
    else:
        reward = f"reward: {data['meta_reward_astral']} AA"
    return f"{name} · {progress} · {reward}"


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
        await interaction.response.defer()
        user = interaction.user
        doc = await self.fetch_key(user, ["progression"])
        endpoints = [
            "account/wizardsvault/daily",
            "account/wizardsvault/weekly",
            "account/wizardsvault/special",
        ]
        daily, weekly, special = await self.call_multiple(endpoints,
                                                          key=doc["key"])
        now = datetime.datetime.now(datetime.timezone.utc)
        embed = discord.Embed(
            title="Wizard's Vault",
            description=(
                f"Daily reset <t:{int(next_daily_reset(now).timestamp())}:R>"
                " · Weekly reset "
                f"<t:{int(next_weekly_reset(now).timestamp())}:R>"),
            color=await self.get_embed_color(interaction))
        for name, data in ("Daily", daily), ("Weekly", weekly):
            if data["objectives"]:
                embed_list_lines(embed,
                                 [objective_line(o) for o in data["objectives"]],
                                 section_name(name, data))
        if special["objectives"]:
            embed_list_lines(embed,
                             [objective_line(o) for o in special["objectives"]],
                             "Special")
        if "wallet" in doc["permissions"]:
            wallet = await self.call_api("account/wallet", key=doc["key"])
            acclaim = next(
                (c["value"] for c in wallet if c["id"] == ASTRAL_ACCLAIM), 0)
            embed.add_field(name="Astral Acclaim", value=acclaim)
        embed.set_author(name=doc["account_name"],
                         icon_url=user.display_avatar.url)
        embed.set_footer(text="AA = Astral Acclaim",
                         icon_url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(WizardsVault(bot))
