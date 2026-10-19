"""Links to the Guild Wars 2 wiki."""
import hashlib

WIKI_URL = "https://wiki.guildwars2.com/wiki/"


def profession_icon_url(name):
    """Wiki URL of the tango icon for a profession or elite specialization."""
    filename = name.title().replace(" ", "_") + "_tango_icon_200px.png"
    digest = hashlib.md5(filename.encode()).hexdigest()
    return ("https://wiki.guildwars2.com/images/"
            f"{digest[0]}/{digest[:2]}/{filename}")


async def page_url(session, name):
    """The wiki page for `name`, or None if it doesn't exist."""
    url = WIKI_URL + name.replace(" ", "_")
    async with session.head(url) as r:
        if not r.status == 200:
            url = None
    return url
