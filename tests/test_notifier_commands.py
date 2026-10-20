"""/notifier news, update and bosses."""
import pytest

import subject


def channel(**permissions):
    return subject.RecordingChannel(5, 10, **permissions)


# --- /notifier news ----------------------------------------------------------------------------


async def test_news_enable_with_a_role():
    from unittest.mock import MagicMock

    sent, writes = await subject.notifier_command("news", enabled=True, channel=channel(), mention=MagicMock(id=77))
    assert sent == "I will now send news to <#5>."
    assert writes == [(10, "set", {"news.on": True, "news.channel": 5, "news.role": 77})]


async def test_news_needs_a_channel_and_permissions():
    sent, _ = await subject.notifier_command("news", enabled=True)
    assert sent == "You must specify a channel."
    sent, writes = await subject.notifier_command("news", enabled=True, channel=channel(can_send=False))
    assert sent == "I do not have permissions to send messages to <#5>"
    sent, writes = await subject.notifier_command("news", enabled=True, channel=channel(can_embed=False))
    assert sent == "I do not have permissions to embed links in <#5>"
    assert writes == []


async def test_news_disable():
    sent, writes = await subject.notifier_command("news", settings={"news": {"on": True}}, enabled=False)
    assert sent == "News notifier disabled."
    assert writes == [(10, "set", {"news.on": False})]
    sent, writes = await subject.notifier_command("news", enabled=False)
    assert sent.startswith("News notifier is aleady disabled.")
    assert writes == []


# --- /notifier update ----------------------------------------------------------------------------


async def test_update_enable_and_disable():
    from unittest.mock import MagicMock

    sent, writes = await subject.notifier_command("update", enabled=True, channel=channel(),
                                                  mention=MagicMock(mention="<@&77>"))
    assert sent == "I will now send update notifications to <#5>."
    assert writes == [(10, "set", {"updates.on": True, "updates.channel": 5, "updates.mention": "<@&77>"})]
    sent, writes = await subject.notifier_command("update", settings={"updates": {"on": True}}, enabled=False)
    assert (sent, writes) == ("Update notifier disabled.", [(10, "set", {"updates.on": False})])


# --- /notifier bosses ----------------------------------------------------------------------------


async def test_bosses_enable_and_disable():
    sent, writes = await subject.notifier_command("bosses", enabled=True, channel=channel(), behavior="edit")
    assert sent == "I will now send boss notifications to <#5>."
    assert writes == [(10, "set", {"bossnotifs.on": True, "bossnotifs.channel": 5, "bossnotifs.edit": True})]
    sent, writes = await subject.notifier_command("bosses", settings={"bossnotifs": {"on": True}}, enabled=False)
    assert (sent, writes) == ("Boss notifier disabled.", [(10, "set", {"bossnotifs.on": False})])


# --- Fixes -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("command, key, message", [
    ("news", "news", "News notifier disabled."),
    ("bosses", "bossnotifs", "Boss notifier disabled."),
])
async def test_disabling_with_a_channel_disables(command, key, message):
    sent, writes = await subject.notifier_command(command, settings={key: {"on": True}}, enabled=False,
                                                  channel=channel())
    assert sent == message
    assert writes == [(10, "set", {f"{key}.on": False})]
