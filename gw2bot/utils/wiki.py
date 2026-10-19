"""Links to the Guild Wars 2 wiki."""
import asyncio
import hashlib

import aiohttp

WIKI_URL = "https://wiki.guildwars2.com/wiki/"
# The link is optional; don't hold up the reply for long
TIMEOUT = aiohttp.ClientTimeout(total=5)


def profession_icon_url(name):
    """Wiki URL of the tango icon for a profession or elite specialization."""
    filename = name.title().replace(" ", "_") + "_tango_icon_200px.png"
    digest = hashlib.md5(filename.encode()).hexdigest()
    return ("https://wiki.guildwars2.com/images/"
            f"{digest[0]}/{digest[:2]}/{filename}")


async def page_url(session, name):
    """The wiki page for `name`, or None if it doesn't exist or the wiki
    can't be reached."""
    url = WIKI_URL + name.replace(" ", "_")
    try:
        async with session.head(url, timeout=TIMEOUT) as r:
            if not r.status == 200:
                url = None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        url = None
    return url
