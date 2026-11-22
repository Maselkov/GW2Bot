"""The English text the catalogs translate, collected from the code: for
scripts/i18n_extract.py and the catalog tests. Not used by the running bot.

Three sources:
- slash command metadata: command, group and option descriptions and choice
  names, exactly as discord.py hands them to the translator;
- calls marked in the code: `<anything>.t(lang, "text", ...)` and
  `N_("text")`, with a string literal;
- display text from the bundled game data (added as the cogs use it).
"""
import ast
import importlib
import pathlib

import discord
from discord import app_commands
from discord.ext import commands

from .i18n import LANGUAGE_NAMES

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent

# Kinds of source string
COMMAND = "command"  # Shown in Discord's command picker: at most 100 characters
CODE = "code"


class _Recorder(app_commands.Translator):
    """Records what discord.py asks to translate, translating nothing."""

    def __init__(self):
        self.strings = set()

    async def translate(self, string, locale, context):
        self.strings.add((string.message, context.location))
        return None


def cog_classes():
    """Every cog class in the bot's extensions."""
    from .bot import extensions

    for name in extensions():
        module = importlib.import_module(name)
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, commands.Cog) and value.__module__ == module.__name__:
                yield value


async def command_strings():
    """{text: TranslationContextLocation} for every description and choice
    name of the bot's slash commands (names are never translated)."""
    from .i18n import _UNTRANSLATED_LOCATIONS

    recorder = _Recorder()
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    for cog in cog_classes():
        for command in cog.__cog_app_commands__:
            await command.get_translated_payload(tree, recorder)
    await client.close()
    return {
        text: location
        for text, location in recorder.strings
        if location not in _UNTRANSLATED_LOCATIONS
        # Languages are offered in their own names; "…" is discord.py's
        # description for options without one
        and text not in LANGUAGE_NAMES.values() and text != "…"
    }


def _marked_strings(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "t" and len(node.args) >= 2:
            text = node.args[1]
        elif isinstance(func, ast.Name) and func.id == "N_" and node.args:
            text = node.args[0]
        else:
            continue
        if isinstance(text, ast.Constant) and isinstance(text.value, str):
            yield text.value


# Display text in the bundled game data: (file, path, what), where `what`
# says which part of the value at `path` is text: "values" of a {key: text}
# map, "keys" of a {text: data} map, or the "items" of a list
GAMEDATA_TEXT = [
    ("gamedata", ("items", "types"), "values"),
    ("gamedata", ("fractals",), "keys"),
    ("instabilities", ("instability_names",), "items"),
]


def gamedata_strings():
    """The display text in the bundled game data the cogs translate."""
    from .gamedata import event_timer_names, killproof_names, load_gamedata

    gamedata, instabilities = load_gamedata()
    files = {"gamedata": gamedata, "instabilities": instabilities}
    for file, path, what in GAMEDATA_TEXT:
        value = files[file]
        for key in path:
            value = value[key]
        yield from value.values() if what == "values" else value
    yield from event_timer_names(gamedata["event_timers"])
    yield from killproof_names(gamedata["killproofs"])


def code_strings(directory=PACKAGE_DIR):
    """{text: [where]} for the text marked for translation in the code."""
    found = {}
    for path in sorted(pathlib.Path(directory).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for text in _marked_strings(tree):
            found.setdefault(text, []).append(str(path.relative_to(PACKAGE_DIR.parent)))
    return found


async def source_strings():
    """{English text: kind} for everything the catalogs should translate."""
    sources = {text: CODE for text in code_strings()}
    sources.update({text: CODE for text in gamedata_strings()})
    # Command metadata last: its length limit is the stricter
    sources.update({text: COMMAND for text in await command_strings()})
    return sources
