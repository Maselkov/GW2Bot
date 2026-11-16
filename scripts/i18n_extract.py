"""Update the catalogs in gw2bot/locales/ from the code: add the English text
that's new (with an empty translation, to be filled in) and report or remove
text the code no longer has. Run from the repository root:

    .venv/bin/python scripts/i18n_extract.py          # add new text
    .venv/bin/python scripts/i18n_extract.py --prune  # also remove old text

See gw2bot/i18n_sources.py for where the text comes from, and
gw2bot/locales/STYLE.md for how to translate it.
"""
import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gw2bot.i18n import LANGUAGES, LOCALES_DIR  # noqa: E402
from gw2bot.i18n_sources import source_strings  # noqa: E402


def load(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, catalog):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(catalog.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")


async def main(prune):
    sources = await source_strings()
    for language in LANGUAGES[1:]:
        path = LOCALES_DIR / f"{language}.json"
        catalog = load(path)
        added = [text for text in sources if text not in catalog]
        stale = [text for text in catalog if text not in sources]
        for text in added:
            catalog[text] = ""
        if prune:
            for text in stale:
                del catalog[text]
        save(path, catalog)
        untranslated = sum(1 for text in sources if not catalog.get(text))
        print(f"{language}: {len(added)} added, {len(stale)} {'removed' if prune else 'no longer used'}, "
              f"{untranslated} of {len(sources)} untranslated")
        if stale and not prune:
            for text in stale:
                print(f"  no longer used: {text!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prune", action="store_true", help="remove text the code no longer has")
    asyncio.run(main(parser.parse_args().prune))
