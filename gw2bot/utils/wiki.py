"""Links to the Guild Wars 2 wiki."""
import asyncio
import hashlib
import urllib.parse

import aiohttp

# Each language's wiki
WIKIS = {
    "en": "https://wiki.guildwars2.com",
    "de": "https://wiki-de.guildwars2.com",
    "fr": "https://wiki-fr.guildwars2.com",
    "es": "https://wiki-es.guildwars2.com",
}
# Each wiki's search page, for (wiki, quoted search text)
SEARCH_URLS = {
    "en": "{}/index.php?title=Special%3ASearch&search={}",
    "de": "{}/index.php?search={}&title=Spezial%3ASuche&",
    "fr": "{}/index.php?search={}&title=Spécial%3ARecherche",
    "es": "{}/index.php?title=Especial%3ABuscar&search={}",
}
WIKI_URL = WIKIS["en"] + "/wiki/"
# The link is optional; don't hold up the reply for long
TIMEOUT = aiohttp.ClientTimeout(total=5)


def profession_icon_url(name):
    """Wiki URL of the tango icon for a profession or elite specialization."""
    filename = name.title().replace(" ", "_") + "_tango_icon_200px.png"
    digest = hashlib.md5(filename.encode()).hexdigest()
    return ("https://wiki.guildwars2.com/images/"
            f"{digest[0]}/{digest[:2]}/{filename}")


def article_url(name, lang="en"):
    """The URL of the page `name` on the `lang` wiki."""
    return f"{WIKIS[lang]}/wiki/{name.replace(' ', '_')}"


def search_url(text, lang="en"):
    """The URL of a search for `text` on the `lang` wiki."""
    return SEARCH_URLS[lang].format(WIKIS[lang], urllib.parse.quote(text))


async def page_url(session, name, lang="en", english_name=None):
    """The page for `name` on the `lang` wiki or, if it has none, for
    `english_name` on the English wiki. None if there's no page or the wiki
    can't be reached."""
    candidates = [article_url(name, lang)]
    if lang != "en" and english_name:
        candidates.append(article_url(english_name))
    for url in candidates:
        try:
            async with session.head(url, timeout=TIMEOUT) as r:
                if r.status == 200:
                    return url
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # The wiki is down: the English one is the same servers
            return None
    return None
