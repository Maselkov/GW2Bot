"""Notifier loops: one run each, against fakes."""
import subject

# 2500 copper per gem: 400 gems cost 100 gold
PRICE = (200, {"coins_per_gem": 2500, "quantity": 4000})


async def test_gem_tracker_notifies_once_the_price_drops():
    sent, writes, error = await subject.run_gem_tracker([PRICE], {1: 1_100_000, 2: 900_000})
    assert error is None
    assert sent == [(1, "Hey, <@1>! You asked to be notified when 400 gems were cheaper than 110 gold . "
                        "Guess what? They're now only 100 gold !")]
    # Notified users stop tracking; the other keeps waiting
    assert writes == [(1, "set", {"gemtrack": None})]


async def test_gem_tracker_survives_api_errors(caplog):
    # discord.py stops a task loop for good on any exception but network
    # errors, so a bad API response must not escape
    sent, writes, error = await subject.run_gem_tracker([(500, {"text": "error"})], {1: 1_100_000})
    assert error is None
    assert sent == writes == []
    assert "Couldn't check the gem price" in caplog.text


# --- News ------------------------------------------------------------------------------


def feed(*titles):
    items = "".join(
        f"<item><title>{t}</title><link>https://www.guildwars2.com/en/news/{i}/</link>"
        f"<description>&lt;p&gt;About {t}&lt;/p&gt;&lt;p&gt;More&lt;/p&gt;</description></item>"
        for i, t in enumerate(titles)
    )
    return f"<rss><channel>{items}</channel></rss>"


NEWS_SERVERS = {10: {"news": {"on": True, "channel": 5}}, 11: {"news": {"on": False, "channel": 6}}}


async def test_news_posts_new_items_to_enabled_servers():
    channel, other = subject.text_channel(5), subject.text_channel(6, guild_id=11)
    config, _, error = await subject.run_news_checker(
        feed("New Release", "Old News"), ["Old News"], NEWS_SERVERS, [channel, other]
    )
    assert error is None
    assert [(content, embed["title"], embed["description"]) for content, embed in channel.sent] == [
        (None, "New Release", "[Click here](https://www.guildwars2.com/en/news/0/)\nAbout New Release"),
    ]
    assert other.sent == []
    assert config == [{"cache.news": ["New Release", "Old News"]}]


async def test_news_first_run_only_remembers_the_feed():
    channel = subject.text_channel(5)
    config, _, _ = await subject.run_news_checker(feed("A", "B"), [], NEWS_SERVERS, [channel])
    assert channel.sent == []
    assert config == [{"cache.news": ["A", "B"]}]


async def test_news_filters_streams_and_showcases():
    channel = subject.text_channel(5)
    await subject.run_news_checker(
        feed("The ArenaNet Streaming Schedule", "Community Showcase: Art", "Patch"), ["Old"], NEWS_SERVERS, [channel]
    )
    assert [embed["title"] for _, embed in channel.sent] == ["Patch"]


async def test_news_survives_a_feed_that_isnt_xml(caplog):
    channel = subject.text_channel(5)
    config, _, error = await subject.run_news_checker(
        "<html>Just a moment...</html><script>", ["Old"], NEWS_SERVERS, [channel]
    )
    assert error is None
    assert channel.sent == config == []
    assert "Couldn't check the news" in caplog.text


# --- Game updates --------------------------------------------------------------------------


async def test_game_update_checker_survives_a_bad_build_page(caplog):
    assert await subject.run_game_update_checker({"cache": {"build": "100"}}, "") is None
    assert "Couldn't check for game updates" in caplog.text


async def test_game_update_checker_survives_a_missing_config(caplog):
    assert await subject.run_game_update_checker(None, "100 200") is None


async def test_news_mentions_the_role():
    from unittest.mock import MagicMock

    channel = subject.text_channel(5)
    channel.guild.get_role = lambda role_id: MagicMock(mention="<@&77>") if role_id == 77 else None
    servers = {10: {"news": {"on": True, "channel": 5, "role": 77}}}
    await subject.run_news_checker(feed("New Release"), ["Old"], servers, [channel])
    assert [content for content, _ in channel.sent] == ["<@&77>"]


async def test_news_turns_itself_off_without_permission():
    import discord
    from unittest.mock import MagicMock

    channel = subject.text_channel(5)
    channel.send.side_effect = discord.Forbidden(MagicMock(status=403), "Missing Permissions")
    _, writes, error = await subject.run_news_checker(feed("New Release"), ["Old"], NEWS_SERVERS, [channel])
    assert error is None
    assert writes == [(10, "set", {"news.on": False})]


# --- Game updates: build check and posting ---------------------------------------------


def update_embed(title="Game Update Notes: March 5, 2024"):
    import discord

    embed = discord.Embed(title=title)
    embed.add_field(name="Update Notes", value="Notes")
    return embed


UPDATE_SERVERS = {
    10: {"updates": {"on": True, "channel": 5, "mention": "<@&77>"}},
    11: {"updates": {"on": True, "channel": 6, "mention": "everyone"}},
    12: {"updates": {"on": True, "channel": 7}},
    13: {"updates": {"on": False, "channel": 8}},
}


def update_channels():
    return [subject.RecordingChannel(5, 10), subject.RecordingChannel(6, 11),
            subject.RecordingChannel(7, 12, can_embed=False), subject.RecordingChannel(8, 13)]


async def test_a_new_build_rebuilds_the_cache():
    result = await subject.check_game_updates({"cache": {"build": "100"}}, "101 0 0 0")
    assert result["rebuilt"]
    assert result["config"] == [{"cache.build": "101"}]
    result = await subject.check_game_updates({"cache": {"build": "101"}}, "101 0 0 0")
    assert not result["rebuilt"]
    assert result["config"] == []


async def test_update_notes_go_to_enabled_servers():
    channels = update_channels()
    notes = [(update_embed(), "Guild Wars 2 has just updated!", False)]
    await subject.check_game_updates({"cache": {"build": "101"}}, "101", notes=notes, servers=UPDATE_SERVERS,
                                     channels=channels)
    # The saved mention (legacy "everyone" gets its @), or the text alone
    # without embed permission
    assert [(content, embed and embed["title"]) for c in channels for content, embed, _ in c.sent] == [
        ("<@&77> Guild Wars 2 has just updated!", "Game Update Notes: March 5, 2024"),
        ("@everyone Guild Wars 2 has just updated!", "Game Update Notes: March 5, 2024"),
        ("Guild Wars 2 has just updated!", None),
    ]


async def test_hotfixes_dont_mention():
    channels = update_channels()
    notes = [(update_embed(), "Guild Wars 2 has just updated!", True)]
    await subject.check_game_updates({"cache": {"build": "101"}}, "101", notes=notes, servers=UPDATE_SERVERS,
                                     channels=channels)
    assert channels[0].sent[0][0] == "Guild Wars 2 has just updated!"


# --- Gem tracker: undeliverable users ------------------------------------------------------------


async def test_gem_tracker_keeps_users_it_cant_dm():
    # Closed DMs (9xx in the fake) are retried on the next run
    sent, writes, error = await subject.run_gem_tracker([PRICE], {950: 1_100_000, 1: 1_100_000})
    assert error is None
    assert [user for user, _ in sent] == [1]
    assert writes == [(1, "set", {"gemtrack": None})]
