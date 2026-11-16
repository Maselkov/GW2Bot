"""Build gw2bot/locales/glossary.json: the official German, French and
Spanish names of the game terms the bot's text uses, so translations use the
names players see in their game client.

Sources (gw2bot/locales/glossary_sources.json):
- the GW2 API in each language, for terms with an id (professions, items,
  skills, maps, currencies...);
- the wikis' interlanguage links, for terms the API doesn't name
  (expansions, game modes, features...): the English page's links, and the
  language wikis' links back to it.

Interlanguage links are written by wiki editors and are sometimes wrong (a
page can link to a broader or neighbouring topic), so check new entries
before relying on them.

gw2bot/locales/glossary_overrides.json holds corrections checked by hand,
which replace what the script finds.

Terms neither source resolves are listed at the end for a person to look
up; they're never guessed. Run from the repository root:

    .venv/bin/python scripts/i18n_glossary.py
"""
import asyncio
import json
import pathlib
import sys

import aiohttp

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCALES = ROOT / "gw2bot" / "locales"
LANGUAGES = ("de", "fr", "es")
API_URL = "https://api.guildwars2.com/v2/"
EN_WIKI_API = "https://wiki.guildwars2.com/api.php"
WIKI_API = "https://wiki-{}.guildwars2.com/api.php"
# Identify the tool honestly; the wikis allow API clients that do
USER_AGENT = "GW2Bot-i18n-glossary/1.0 (https://github.com/Maselkov/GW2Bot)"
TIMEOUT = aiohttp.ClientTimeout(total=30)
ATTEMPTS = 3


async def get_json(session, url, params):
    """The JSON at `url`, or None if it can't be had (after retries)."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            async with session.get(url, params=params) as r:
                if r.status == 200:
                    return await r.json()
                if r.status < 500:
                    print(f"{url} answered {r.status} for {params}", file=sys.stderr)
                    return None
        except (aiohttp.ClientError, TimeoutError):
            pass
        await asyncio.sleep(2 * attempt)
    print(f"{url} failed for {params}", file=sys.stderr)
    return None


async def from_api(session, path):
    names = {}
    for language in LANGUAGES:
        data = await get_json(session, API_URL + path, {"lang": language})
        if not data:
            return None
        names[language] = data["name"]
    return names


async def from_wiki(session, title):
    """The language wikis' names for the English wiki page `title`: the
    English page's interlanguage links, completed with the language wikis'
    links back to it (some pages are only linked one way)."""
    params = {
        "action": "query",
        "titles": title,
        "redirects": 1,
        "prop": "langlinks",
        "lllimit": 500,
        "format": "json",
    }
    query = (await get_json(session, EN_WIKI_API, params) or {}).get("query", {})
    # A redirect to a section names something smaller than the page
    if any("tofragment" in redirect for redirect in query.get("redirects", [])):
        return {}
    names = {}
    for page in query.get("pages", {}).values():
        for link in page.get("langlinks", []):
            if link["lang"] in LANGUAGES:
                names[link["lang"]] = link["*"]
        # The page's title after redirects, for the links back to it
        title = page["title"]
    for language in LANGUAGES:
        if language in names:
            continue
        params = {
            "action": "query",
            "list": "langbacklinks",
            "lbllang": "en",
            "lbltitle": title,
            "format": "json",
        }
        data = await get_json(session, WIKI_API.format(language), params)
        if not data:
            continue
        links = data["query"]["langbacklinks"]
        # Articles only, not user pages or other namespaces
        articles = [link["title"] for link in links if link["ns"] == 0]
        if articles:
            names[language] = articles[0]
        # Be gentle with the wikis
        await asyncio.sleep(0.5)
    await asyncio.sleep(0.5)
    return names


async def main():
    with open(LOCALES / "glossary_sources.json", encoding="utf-8") as f:
        sources = json.load(f)
    glossary = {}
    missing = []
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as session:
        for term, path in sources["api"].items():
            names = await from_api(session, path)
            if names:
                glossary[term] = {**names, "source": "api:" + path}
            else:
                missing.append((term, LANGUAGES))
        for title in sources["wiki"]:
            names = await from_wiki(session, title)
            if names:
                glossary[title] = {**names, "source": "wiki"}
            unresolved = [language for language in LANGUAGES if language not in names]
            if unresolved:
                missing.append((title, unresolved))
    # Corrections checked by hand win over what was found
    with open(LOCALES / "glossary_overrides.json", encoding="utf-8") as f:
        overrides = json.load(f)
    for term, names in overrides.items():
        if term.startswith("_"):
            continue
        names = {language: names[language] for language in LANGUAGES if language in names}
        glossary[term] = {**glossary.get(term, {}), **names, "source": "reviewed"}
        missing = [(t, [lang for lang in langs if lang not in names]) if t == term else (t, langs)
                   for t, langs in missing]
        missing = [(t, langs) for t, langs in missing if langs]
    with open(LOCALES / "glossary.json", "w", encoding="utf-8") as f:
        json.dump(dict(sorted(glossary.items(), key=lambda item: item[0].lower())), f,
                  ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"{len(glossary)} terms written to {LOCALES / 'glossary.json'}")
    if missing:
        print("\nNot found (look these up by hand):")
        for term, languages in missing:
            print(f"  {term}: {', '.join(languages)}")


if __name__ == "__main__":
    asyncio.run(main())
