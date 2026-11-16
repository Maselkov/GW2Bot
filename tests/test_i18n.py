"""Translations: choosing a language, the catalogs, and the translator that
localizes slash commands."""
import asyncio

import discord
import pytest
from discord.app_commands import TranslationContext, TranslationContextLocation, locale_str

import subject
from gw2bot.i18n import (
    DISCORD_TEXT_LIMIT,
    LANGUAGES,
    Catalog,
    GW2Translator,
    format_number,
    language_for_locale,
    localized,
    localized_doc,
    placeholders,
)
from gw2bot.i18n_sources import COMMAND, command_strings, source_strings

Locale = discord.Locale
TRANSLATED = LANGUAGES[1:]


# --- Choosing a language ---------------------------------------------------


@pytest.mark.parametrize(
    "locale, language",
    [
        (Locale.american_english, "en"),
        (Locale.british_english, "en"),
        (Locale.german, "de"),
        (Locale.french, "fr"),
        (Locale.spain_spanish, "es"),
        (Locale.latin_american_spanish, "es"),
        (Locale.japanese, None),
        ("not a locale", None),
    ],
)
def test_discord_locales_map_to_the_apis_languages(locale, language):
    assert language_for_locale(locale) == language


async def test_replies_follow_the_users_discord_language():
    assert await subject.reply_language(Locale.latin_american_spanish) == "es"


async def test_the_users_language_setting_beats_their_discord_language():
    assert await subject.reply_language(Locale.french, {"language": "de"}) == "de"


async def test_replies_are_in_english_when_the_bot_doesnt_speak_the_users_language():
    assert await subject.reply_language(Locale.japanese) == "en"


async def test_server_posts_follow_the_servers_discord_language():
    assert await subject.server_language(Locale.french) == "fr"


async def test_the_servers_language_setting_beats_its_discord_language():
    assert await subject.server_language(Locale.french, {"language": "es"}) == "es"


async def test_server_posts_are_in_english_when_the_bot_doesnt_speak_its_language():
    assert await subject.server_language(Locale.korean) == "en"


async def test_dms_outside_interactions_use_the_users_setting_else_english():
    assert await subject.dm_language({"language": "fr"}) == "fr"
    assert await subject.dm_language() == "en"


# --- The API ---------------------------------------------------------------


async def test_api_requests_ask_for_text_in_a_language():
    session = subject.FakeSession((200, {"id": 2, "name": "Karma"}))
    await subject.api_get(session, "currencies/2", lang="de")
    (_, params, _), = session.requests
    assert params == {"lang": "de"}


async def test_api_requests_without_a_language_get_the_apis_default():
    session = subject.FakeSession((200, {"id": 2, "name": "Karma"}))
    await subject.api_get(session, "currencies/2")
    (_, params, _), = session.requests
    assert "lang" not in params


# --- Catalogs --------------------------------------------------------------


def test_text_without_a_translation_stays_in_english():
    catalog = Catalog({"de": {"Shows your wallet": "Zeigt Eure Geldbörse", "Untranslated": ""}})
    assert catalog.t("de", "Shows your wallet") == "Zeigt Eure Geldbörse"
    assert catalog.t("de", "Untranslated") == "Untranslated"
    assert catalog.t("de", "Not in the catalog") == "Not in the catalog"
    assert catalog.t("en", "Shows your wallet") == "Shows your wallet"


def test_placeholders_are_filled_in_the_translation():
    catalog = Catalog({"de": {"{count} of {total}": "{count} von {total}"}})
    assert catalog.t("de", "{count} of {total}", count=3, total=5) == "3 von 5"


@pytest.fixture(scope="module")
def sources():
    # Collected once: it walks every command of every cog
    return asyncio.run(source_strings())


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load()


@pytest.mark.parametrize("language", TRANSLATED)
def test_all_text_is_translated(sources, catalog, language):
    untranslated = [text for text in sources if not catalog.get(language, text)]
    assert not untranslated, "run scripts/i18n_extract.py and translate (gw2bot/locales/STYLE.md)"


@pytest.mark.parametrize("language", TRANSLATED)
def test_catalogs_have_no_text_the_code_no_longer_uses(sources, catalog, language):
    stale = [text for text in catalog.translations[language] if text not in sources]
    assert not stale, "run scripts/i18n_extract.py --prune"


@pytest.mark.parametrize("language", TRANSLATED)
def test_translations_only_use_the_texts_placeholders(catalog, language):
    # A translation may leave one out, e.g. use {rarity} where English
    # uses {rarity_lower}
    for text, translation in catalog.translations[language].items():
        if translation:
            assert placeholders(translation) <= placeholders(text), (text, translation)


@pytest.mark.parametrize("language", TRANSLATED)
def test_command_text_fits_discords_limit(sources, catalog, language):
    for text, kind in sources.items():
        translation = catalog.get(language, text)
        if kind == COMMAND and translation:
            assert len(translation) <= DISCORD_TEXT_LIMIT, translation


# --- Slash commands --------------------------------------------------------


def context(location):
    return TranslationContext(location=location, data=None)


async def test_command_descriptions_and_choices_are_translated(catalog):
    translator = GW2Translator(Catalog({"de": {"Shows your wallet": "Zeigt Eure Geldbörse", "All": "Alle"}}))
    description = context(TranslationContextLocation.command_description)
    choice = context(TranslationContextLocation.choice_name)
    assert await translator.translate(locale_str("Shows your wallet"), Locale.german, description) == \
        "Zeigt Eure Geldbörse"
    assert await translator.translate(locale_str("All"), Locale.german, choice) == "Alle"
    # Discord shows the English text where there's no translation
    assert await translator.translate(locale_str("All"), Locale.french, choice) is None
    assert await translator.translate(locale_str("All"), Locale.japanese, choice) is None


@pytest.mark.parametrize(
    "location",
    [
        TranslationContextLocation.command_name,
        TranslationContextLocation.group_name,
        TranslationContextLocation.parameter_name,
    ],
)
async def test_command_and_option_names_are_never_translated(location):
    # A localized name replaces the English one in Discord's command picker
    translator = GW2Translator(Catalog({"de": {"wallet": "geldbörse"}}))
    assert await translator.translate(locale_str("wallet"), Locale.german, context(location)) is None


async def test_command_text_includes_descriptions_options_and_choices():
    texts = await command_strings()
    assert "Shows your wallet" in texts  # A command
    assert "API key management" in texts  # A group
    assert "The channel to post to." in texts  # An option
    assert "World bosses" in texts  # A choice
    assert "wallet" not in texts  # Names aren't translated
    assert "Deutsch" not in texts  # Languages are offered in their own names


# --- Helpers ---------------------------------------------------------------


def test_cached_documents_name_things_in_the_language_or_else_english():
    doc = {"name": "Banana", "description": "Food", "l10n": {"de": {"name": "Banane"}}}
    assert localized(doc, "de") == "Banane"
    assert localized(doc, "de", "description") == "Food"
    assert localized(doc, "fr") == "Banana"
    assert localized(doc, "en") == "Banana"


BANANA = {
    "_id": 12251, "name": "Banana", "rarity": "Basic",
    "details": {"type": "Food", "description": "+40 Power"},
    "l10n": {"de": {"name": "Banane", "details": {"description": "+40 Kraft"}}},
}


def test_cached_documents_read_in_a_language_have_its_text_and_english_elsewhere():
    assert localized_doc(BANANA, "de") == {
        "_id": 12251, "name": "Banane", "rarity": "Basic",
        "details": {"type": "Food", "description": "+40 Kraft"},
    }
    english = {k: v for k, v in BANANA.items() if k != "l10n"}
    assert localized_doc(BANANA, "fr") == english
    assert localized_doc(BANANA, "en") == english
    # The cached document itself is unchanged
    assert BANANA["name"] == "Banana"
    assert localized_doc(None, "de") is None


def test_nested_fields_are_read_in_a_language():
    assert localized(BANANA, "de", "details.description") == "+40 Kraft"
    assert localized(BANANA, "de", "details.type") == "Food"
    assert localized(BANANA, "es", "details.description") == "+40 Power"


@pytest.mark.parametrize(
    "language, text",
    [("en", "1,234,567"), ("de", "1.234.567"), ("fr", "1 234 567"), ("es", "1.234.567")],
)
def test_numbers_use_the_languages_thousands_separator(language, text):
    assert format_number(1234567, language) == text


# --- Language settings -----------------------------------------------------


async def test_users_choose_their_language():
    sent, writes = await subject.language_command("fr", locale=Locale.german)
    assert writes == [("set", {"language": "fr"})]
    # Confirmed in the new language
    assert sent == "Le bot vous répond désormais en Français."


async def test_users_go_back_to_their_discord_language():
    sent, writes = await subject.language_command("auto", locale=Locale.spain_spanish)
    assert writes == [("unset", {"language": ""})]
    assert sent == "El bot ahora te responde en tu idioma de Discord, Español."


async def test_users_whose_discord_language_the_bot_doesnt_speak_are_told():
    sent, _ = await subject.language_command("auto", locale=Locale.japanese)
    assert "doesn't speak yours, so it answers you in English" in sent


async def test_servers_choose_the_language_of_their_posts():
    sent, settings = await subject.server_language_command("es", locale=Locale.german)
    assert settings == {"language": "es"}
    # The admin is answered in their own language
    assert sent.startswith("Der Bot postet auf diesem Server jetzt auf Español.")


async def test_servers_go_back_to_their_discord_language():
    sent, settings = await subject.server_language_command("auto", server_locale=Locale.french)
    assert settings == {}
    assert sent.startswith("The bot now posts in this server's Discord language, Français.")
