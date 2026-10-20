"""/daily and /notifier daily."""
import datetime
import zoneinfo


import subject


async def test_daily_all():
    embed = await subject.daily_command(subject.DAILY_CACHE, category="all")
    assert embed["title"] == "Dailies"
    names = [f["name"] for f in embed["fields"]]
    # The agents now, and after their next reset
    assert names[0] == "PSNA"
    assert names[1].startswith("PSNA <t:")
    assert {"> Daily Fractals", "> CM Instabilities", "RAID BOUNTIES", "LIVING WORLD SEASON 3"} <= set(names)


async def test_daily_one_category_tomorrow():
    embed = await subject.daily_command(subject.DAILY_CACHE, category="raids", tomorrow=True)
    assert embed["title"] == "Dailies tomorrow"
    assert [(f["name"], f["value"]) for f in embed["fields"]] == [("RAID BOUNTIES", "Vale Guardian")]


async def test_daily_before_the_cache_is_ready():
    sent = await subject.daily_command(None, category="all")
    assert sent == "Dailies are currently unavailable. Try again in a bit"


# --- /notifier daily ----------------------------------------------------------------------


async def test_notifier_daily_setup():
    sent, (content, embed), writes = await subject.notifier_daily(choose=["raids"], pin_message=True,
                                                                  behavior="autoedit")
    assert sent == "** **"
    assert content == "I will now send dailies to <#5>. Here's an example notification:"
    assert [f["name"] for f in embed["fields"]] == ["RAID BOUNTIES"]
    assert writes == [(10, "set", {
        "daily.on": True, "daily.channel": 5, "daily.autopin": True, "daily.autodelete": False,
        "daily.autoedit": True, "daily.categories": ["raids"],
    })]


async def test_notifier_daily_disable():
    sent, _, writes = await subject.notifier_daily(enabled=False, already_enabled=True)
    assert sent == "Daily notifier disabled."
    assert writes == [(10, "set", {"daily.on": False})]


async def test_notifier_daily_dropdown_times_out():
    sent, final, writes = await subject.notifier_daily()
    assert final == ("No response in time.", None)
    assert writes == []


async def test_daily_timestamp_on_a_server_outside_utc():
    # Freezing the clock at a Helsinki time also runs the bot in Helsinki time
    now = datetime.datetime(2024, 3, 6, 14, 30, tzinfo=zoneinfo.ZoneInfo("Europe/Helsinki"))
    embed = await subject.daily_command(subject.DAILY_CACHE, category="raids", now=now)
    assert datetime.datetime.fromisoformat(embed["timestamp"]) == now
