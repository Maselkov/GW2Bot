"""Translations: the languages the GW2 API serves (English, German, French,
Spanish), message catalogs keyed by the English text, and the translator that
localizes slash command descriptions and choices.

Command, group and option names are never localized: Discord shows a
localized name instead of the English one, which would make commands differ
between users.
"""
import json
import pathlib
import string

import discord
from discord import app_commands
from discord.app_commands import TranslationContextLocation

LOCALES_DIR = pathlib.Path(__file__).resolve().parent / "locales"

# The GW2 API's languages, English first (the source language)
LANGUAGES = ("en", "de", "fr", "es")
DEFAULT_LANGUAGE = "en"
# Each language's name in itself, for choosing one
LANGUAGE_NAMES = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español"}

# Discord's locales for each language
_LOCALE_LANGUAGES = {
    discord.Locale.american_english: "en",
    discord.Locale.british_english: "en",
    discord.Locale.german: "de",
    discord.Locale.french: "fr",
    discord.Locale.spain_spanish: "es",
    discord.Locale.latin_american_spanish: "es",
}

# Where the translator leaves the English text (see the module docstring)
_UNTRANSLATED_LOCATIONS = {
    TranslationContextLocation.command_name,
    TranslationContextLocation.group_name,
    TranslationContextLocation.parameter_name,
}

# Discord's limit on descriptions and choice names
DISCORD_TEXT_LIMIT = 100


def language_for_locale(locale):
    """The language for a Discord locale (or its string), or None if the
    bot doesn't speak it."""
    try:
        locale = discord.Locale(str(locale))
    except ValueError:
        return None
    return _LOCALE_LANGUAGES.get(locale)


def resolve_language(*candidates):
    """The first of `candidates` (language codes or Discord locales, any of
    them None) the bot speaks; English if none."""
    for candidate in candidates:
        if candidate is None:
            continue
        if candidate in LANGUAGES:
            return candidate
        language = language_for_locale(candidate)
        if language:
            return language
    return DEFAULT_LANGUAGE


def N_(text):
    """Marks `text` for translation where it's defined, for text translated
    later with Catalog.t (headings in a table, choices built in a loop...).
    Returns it unchanged."""
    return text


async def interaction_language(users, interaction):
    """The language to answer `interaction` in: the user's /language
    setting (from the `users` settings), else their Discord client's
    language, else English."""
    settings = await users.get(interaction.user.id)
    return resolve_language(settings.get("language"), interaction.locale)


def placeholders(text):
    """The names of `text`'s format placeholders."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


class Catalog:
    """Translations of English text, from locales/<language>.json: flat
    {English text: translation} maps. An empty translation means not
    translated yet."""

    def __init__(self, translations=None):
        # {language: {English text: translation}}
        self.translations = translations if translations is not None else {}

    @classmethod
    def load(cls, directory=LOCALES_DIR):
        translations = {}
        for language in LANGUAGES[1:]:
            path = pathlib.Path(directory) / f"{language}.json"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    translations[language] = json.load(f)
        return cls(translations)

    def get(self, language, text):
        """`text` in `language`, or None if it isn't translated."""
        return self.translations.get(language, {}).get(text) or None

    def t(self, language, text, /, **fields):
        """`text` in `language` (English if it isn't translated), with
        `fields` filled into its {placeholders}."""
        text = self.get(language, text) or text
        return text.format(**fields) if fields else text


class GW2Translator(app_commands.Translator):
    """Localizes command descriptions, option descriptions and choice names
    from the catalog."""

    def __init__(self, catalog):
        self.catalog = catalog

    async def translate(self, string, locale, context):
        if context.location in _UNTRANSLATED_LOCATIONS:
            return None
        language = language_for_locale(locale)
        if not language or language == DEFAULT_LANGUAGE:
            return None
        return self.catalog.get(language, string.message)


# Cached game data documents (items, skills, achievements...) are the API's
# English documents with, under "l10n", what differs in each other language:
# {"name": "Banana", ..., "l10n": {"de": {"name": "Banane"}, ...}}. The API
# gives ids, enums (rarity, type, flags) and icons the same in every
# language, so only text differs. Logic reads the English document (emoji
# names, wiki icons and name matching depend on English); display reads
# localized_doc().


def l10n_diff(english, other):
    """What `other` (the same API document in another language) has that
    differs from `english`: nested documents compared field by field, any
    other value (text, lists) kept whole if it differs."""
    diff = {}
    for name, value in other.items():
        base = english.get(name)
        if isinstance(value, dict) and isinstance(base, dict):
            nested = l10n_diff(base, value)
            if nested:
                diff[name] = nested
        elif value != base:
            diff[name] = value
    return diff


def _merge(doc, diff):
    merged = dict(doc)
    for name, value in diff.items():
        if isinstance(value, dict) and isinstance(merged.get(name), dict):
            merged[name] = _merge(merged[name], value)
        else:
            merged[name] = value
    return merged


def localized_doc(doc, language):
    """A cached game data document with its text in `language` (English
    where it has no translation), without the "l10n" field."""
    if doc is None:
        return None
    translations = doc.get("l10n", {})
    doc = {name: value for name, value in doc.items() if name != "l10n"}
    if language == DEFAULT_LANGUAGE or language not in translations:
        return doc
    return _merge(doc, translations[language])


def localized(doc, language, field="name"):
    """A cached game data document's `field` (dotted for nested fields) in
    `language`, falling back to the English one."""

    def get(value):
        for part in field.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    if language != DEFAULT_LANGUAGE:
        value = get(doc.get("l10n", {}).get(language, {}))
        if value:
            return value
    return get(doc)


# Thousands separators per language
_THOUSANDS = {"en": ",", "de": ".", "fr": " ", "es": "."}


def format_number(number, language=DEFAULT_LANGUAGE):
    """An integer with the language's thousands separator."""
    return "{:,}".format(number).replace(",", _THOUSANDS.get(language, ","))
