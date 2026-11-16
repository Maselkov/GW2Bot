"""Report translations that may not use the official name of a game term:
the English text names a glossary term, but the translation doesn't contain
the glossary's name for it. A report to review, not an error: inflection
(plurals, German cases, Spanish articles) changes the words, and some terms
are deliberately kept in English (see gw2bot/locales/STYLE.md).

    .venv/bin/python scripts/i18n_check.py [de|fr|es ...]
"""
import json
import pathlib
import re
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCALES = ROOT / "gw2bot" / "locales"


def terms(glossary):
    for term, names in glossary.items():
        # Expansion pages are titled "Guild Wars 2: <name>"
        names = {language: name.removeprefix("Guild Wars 2: ") for language, name in names.items()}
        yield term.removeprefix("Guild Wars 2: "), names


def fold(text):
    """Lowercase, without accents."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def stems(name):
    """The start of each word of `name`, so inflected forms match
    (incursión ~ incursiones, Schlachtzug ~ Schlachtzüge)."""
    for word in re.findall(r"\w+", fold(name)):
        yield word if len(word) <= 4 else word[:max(4, len(word) - 2)]


def uses(translation, name):
    translation = fold(translation)
    return all(stem in translation for stem in stems(name))


def mentions(source, term):
    # Not the game's own name, URLs or {placeholders}
    source = re.sub(r"Guild Wars 2|\S+\.\w+/\S*|\S+\.(com|net)\S*|\{\w+\}", "", source)
    return re.search(rf"\b{re.escape(term)}s?\b", source, re.IGNORECASE)


def main(languages):
    with open(LOCALES / "glossary.json", encoding="utf-8") as f:
        glossary = dict(terms(json.load(f)))
    count = 0
    for language in languages:
        with open(LOCALES / f"{language}.json", encoding="utf-8") as f:
            catalog = json.load(f)
        for source, translation in sorted(catalog.items()):
            if not translation:
                continue
            for term, names in glossary.items():
                name = names.get(language)
                if not name or not mentions(source, term):
                    continue
                if not uses(translation, name):
                    count += 1
                    print(f"{language}: {term!r} -> {name!r}?\n    {source}\n    {translation}")
    print(f"{count} to review")


if __name__ == "__main__":
    main(sys.argv[1:] or ["de", "fr", "es"])
