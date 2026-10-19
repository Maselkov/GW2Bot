"""Game update notes: reading the forum, and what gets announced when."""
import datetime
import email.utils

import subject
from gw2bot.utils import update_notes

FEED_URL = update_notes.FEED_URL
TOPIC_URL = "https://en-forum.guildwars2.com/topic/1-game-update-notes-october-13-2026/"


def rss_date(when):
    return email.utils.format_datetime(when)


def feed(
    title="Game Update Notes: October 13, 2026",
    first_post="<p><strong>Halloween</strong> returns!</p>",
    published=None,
):
    from xml.sax.saxutils import escape

    published = published or datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Game Update Notes</title>
  <item>
    <title>{escape(title)}</title>
    <link>{TOPIC_URL}</link>
    <description>{escape(first_post)}</description>
    <pubDate>{rss_date(published)}</pubDate>
  </item>
  <item>
    <title>Game Update Notes: October 6, 2026</title>
    <link>https://en-forum.guildwars2.com/topic/0-older/</link>
    <description>&lt;p&gt;Older&lt;/p&gt;</description>
  </item>
</channel></rss>"""


def topic(*posts):
    articles = "".join(
        f'<article><div data-role="commentContent"><p>{post}</p></div></article>' for post in posts
    )
    return f'<html><body><div id="elPostFeed">{articles}</div></body></html>'


CHALLENGE = (403, "<html><title>Just a moment...</title></html>")


# --- Parsing ---------------------------------------------------------------


def test_parse_feed_takes_newest_thread():
    published = datetime.datetime(2026, 10, 12, 16, 42, 3, tzinfo=datetime.timezone.utc)
    title, link, first_post, when = update_notes.parse_feed(feed(published=published))
    assert title == "Game Update Notes: October 13, 2026"
    assert link == TOPIC_URL
    assert first_post == "<p><strong>Halloween</strong> returns!</p>"
    assert when == published


def test_parse_feed_without_date():
    xml = "<rss><channel><item><title>T</title><link>L</link></item></channel></rss>"
    assert update_notes.parse_feed(xml) == ("T", "L", "", None)


def test_too_old_to_announce():
    now = datetime.datetime(2026, 10, 17, tzinfo=datetime.timezone.utc)
    assert not update_notes.too_old_to_announce(now - datetime.timedelta(hours=47), now)
    assert update_notes.too_old_to_announce(now - datetime.timedelta(hours=49), now)
    assert not update_notes.too_old_to_announce(None, now)


def test_parse_empty_feed():
    assert update_notes.parse_feed("<rss><channel></channel></rss>") is None


def test_parse_topic_posts():
    posts = update_notes.parse_topic_posts(topic("Patch notes", "Hotfix 1"))
    assert [p.count("<p>") for p in posts] == [1, 1]
    assert "Hotfix 1" in posts[1]


def test_parse_challenge_page_has_no_posts():
    assert update_notes.parse_topic_posts(CHALLENGE[1]) == []


def test_notes_to_send():
    posts = ["notes", "hotfix 1", "hotfix 2"]
    assert update_notes.notes_to_send(0, posts) == [("notes", False), ("hotfix 1", True), ("hotfix 2", True)]
    assert update_notes.notes_to_send(2, posts) == [("hotfix 2", True)]
    assert update_notes.notes_to_send(3, posts) == []
    assert update_notes.notes_to_send(5, posts[:1]) == []


# --- Checking every minute -------------------------------------------------


async def test_new_thread_is_announced_once():
    checker = subject.UpdateNotesChecker({FEED_URL: (200, feed()), TOPIC_URL: (200, topic("Patch notes"))})
    assert await checker.check() == [("Game Update Notes: October 13, 2026", "Patch notes", False)]
    assert await checker.check() == []


async def test_hotfix_posts_are_minor():
    pages = {FEED_URL: (200, feed()), TOPIC_URL: (200, topic("Patch notes"))}
    checker = subject.UpdateNotesChecker(pages)
    await checker.check()
    pages[TOPIC_URL] = (200, topic("Patch notes", "Hotfix 1", "Hotfix 2"))
    notes = await checker.check()
    assert [(text, minor) for _, text, minor in notes] == [("Hotfix 1", True), ("Hotfix 2", True)]


async def test_only_the_first_post_mentions_when_several_are_new():
    pages = {FEED_URL: (200, feed()), TOPIC_URL: (200, topic("Patch notes", "Hotfix 1"))}
    notes = await subject.UpdateNotesChecker(pages).check()
    assert [minor for _, _, minor in notes] == [False, True]


async def test_blocked_forum_falls_back_to_feed(caplog):
    pages = {FEED_URL: (200, feed()), TOPIC_URL: CHALLENGE}
    checker = subject.UpdateNotesChecker(pages)
    with caplog.at_level("INFO", logger="tests.update_notes"):
        assert await checker.check() == [
            ("Game Update Notes: October 13, 2026", "**Halloween** returns!", False)
        ]
        assert await checker.check() == []
        assert await checker.check() == []
    # Logged when the forum became unreadable, not on every check
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "HTTP 403" in warnings[0].getMessage()


async def test_hotfixes_follow_once_forum_is_readable_again(caplog):
    pages = {FEED_URL: (200, feed()), TOPIC_URL: CHALLENGE}
    checker = subject.UpdateNotesChecker(pages)
    await checker.check()
    pages[TOPIC_URL] = (200, topic("Patch notes", "Hotfix 1"))
    with caplog.at_level("INFO", logger="tests.update_notes"):
        notes = await checker.check()
    # The first post went out from the feed already
    assert [(text, minor) for _, text, minor in notes] == [("Hotfix 1", True)]
    assert any("readable again" in r.getMessage() for r in caplog.records)


async def test_blocked_forum_never_lowers_the_sent_count():
    pages = {FEED_URL: (200, feed()), TOPIC_URL: (200, topic("Patch notes", "Hotfix 1"))}
    checker = subject.UpdateNotesChecker(pages)
    await checker.check()
    pages[TOPIC_URL] = CHALLENGE
    assert await checker.check() == []
    assert checker.updates.docs[0]["count"] == 2
    pages[TOPIC_URL] = (200, topic("Patch notes", "Hotfix 1", "Hotfix 2"))
    assert [text for _, text, _ in await checker.check()] == ["Hotfix 2"]


async def test_existing_threads_continue_from_their_stored_count():
    pages = {FEED_URL: (200, feed()), TOPIC_URL: (200, topic("Patch notes", "Hotfix 1", "Hotfix 2"))}
    checker = subject.UpdateNotesChecker(pages)
    checker.updates.docs.append({"title": "Game Update Notes: October 13, 2026", "count": 2})
    assert [(text, minor) for _, text, minor in await checker.check()] == [("Hotfix 2", True)]


async def test_unreachable_feed_sends_nothing(caplog):
    checker = subject.UpdateNotesChecker({FEED_URL: (503, "Service unavailable")})
    with caplog.at_level("WARNING", logger="tests.update_notes"):
        assert await checker.check() == []
    assert "feed returned 503" in caplog.records[0].getMessage()


async def test_long_notes_are_truncated_for_the_embed():
    long_post = "<p>" + "word " * 400 + "</p>"
    pages = {FEED_URL: (200, feed(first_post=long_post)), TOPIC_URL: CHALLENGE}
    [(_, text, _)] = await subject.UpdateNotesChecker(pages).check()
    assert len(text) <= 1024
    assert text.endswith(" ...")


async def test_old_thread_first_post_is_not_announced():
    # E.g. a thread first seen while the forum was unreadable, before this fix
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=4)
    pages = {FEED_URL: (200, feed(published=old)), TOPIC_URL: CHALLENGE}
    checker = subject.UpdateNotesChecker(pages)
    checker.updates.docs.append({"title": "Game Update Notes: October 13, 2026", "count": 0})
    assert await checker.check() == []
    assert await checker.check() == []


async def test_old_thread_still_gets_its_hotfixes():
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=4)
    pages = {FEED_URL: (200, feed(published=old)), TOPIC_URL: (200, topic("Patch notes", "Hotfix 1"))}
    notes = await subject.UpdateNotesChecker(pages).check()
    assert [(text, minor) for _, text, minor in notes] == [("Hotfix 1", True)]


def test_parse_feed_unknown_offset_is_utc():
    xml = (
        "<rss><channel><item><title>T</title><link>L</link>"
        "<pubDate>Mon, 12 Oct 2026 16:42:03 -0000</pubDate></item></channel></rss>"
    )
    *_, published = update_notes.parse_feed(xml)
    assert published == datetime.datetime(2026, 10, 12, 16, 42, 3, tzinfo=datetime.timezone.utc)
    assert update_notes.too_old_to_announce(published)
