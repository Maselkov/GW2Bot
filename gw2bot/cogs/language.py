"""/language: the language the bot answers a user in."""
import discord
from discord import app_commands
from discord.app_commands import Choice

from ..i18n import LANGUAGE_NAMES, N_, language_for_locale, resolve_language
from .base import GW2Cog

# The choice for following Discord's language
AUTOMATIC = "auto"


def language_choices():
    """Automatic, then each language in its own name."""
    return [Choice(name=N_("Automatic"), value=AUTOMATIC)] + [
        Choice(name=name, value=code) for code, name in LANGUAGE_NAMES.items()
    ]


class Language(GW2Cog):

    @app_commands.command(name="language")
    @app_commands.describe(language="Automatic follows your Discord language")
    @app_commands.choices(language=language_choices())
    async def language(self, interaction: discord.Interaction, language: str):
        """Choose the language the bot answers you in"""
        if language == AUTOMATIC:
            await self.bot.data.users.update(interaction.user.id, {"language": ""}, op="unset")
            lang = resolve_language(interaction.locale)
            if language_for_locale(interaction.locale):
                text = N_("The bot now answers you in your Discord language, {language}.")
            else:
                text = N_("The bot now follows your Discord language. It doesn't speak yours, "
                          "so it answers you in {language}.")
        else:
            await self.bot.data.users.update(interaction.user.id, {"language": language})
            lang = language
            text = N_("The bot now answers you in {language}.")
        await interaction.response.send_message(
            self.t(lang, text, language=LANGUAGE_NAMES[lang]), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Language(bot))
