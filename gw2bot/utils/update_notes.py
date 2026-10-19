"""Reading game update notes from the official forum."""
import datetime
import email.utils
import xml.etree.ElementTree as et

from bs4 import BeautifulSoup

FEED_URL = "https://en-forum.guildwars2.com/forum/6-game-update-notes.xml"
# A thread's first post is only announced while the thread is this new, so a
# restart (or a thread first seen while the forum was unreadable) doesn't
# announce old patch notes. Threads go up the day before a release.
ANNOUNCE_WITHIN = datetime.timedelta(hours=48)


def parse_feed(xml_text):
    """(title, link, first post HTML, published) of the newest thread in the
    RSS feed. published is a datetime, or None if the feed doesn't say."""
    item = et.fromstring(xml_text).find("channel").find("item")
    if item is None:
        return None
    description = item.find("description")
    published = None
    if item.find("pubDate") is not None:
        try:
            published = email.utils.parsedate_to_datetime(item.find("pubDate").text)
        except (TypeError, ValueError):
            pass
        if published and published.tzinfo is None:
            # "-0000" means UTC with unknown local time
            published = published.replace(tzinfo=datetime.timezone.utc)
    return (
        item.find("title").text,
        item.find("link").text,
        description.text if description is not None and description.text else "",
        published,
    )


def too_old_to_announce(published, now=None):
    if published is None:
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now - published > ANNOUNCE_WITHIN


def parse_topic_posts(html):
    """HTML of each post on a forum topic page, oldest first."""
    soup = BeautifulSoup(html, "html.parser")
    return [str(post) for post in soup.select('#elPostFeed div[data-role="commentContent"]')]


def notes_to_send(sent, posts):
    """[(post HTML, minor)] for posts not sent yet.

    The thread's first post is the patch notes themselves; later posts
    (hotfixes) are minor updates, sent without mentions.
    """
    return [(post, index > 0) for index, post in enumerate(posts) if index >= sent]
