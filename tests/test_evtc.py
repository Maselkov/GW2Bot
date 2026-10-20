"""EVTC logs: uploading to dps.report, the report embed, autoposting and destinations."""
import datetime

import pytest

import subject

UTC = datetime.timezone.utc
DPS_REPORT = "https://dps.report/"


def player(name, account, profession, dps, *, group=1, downs=0, guild="GUILD-A", might=20.0, quickness=95.0):
    return {
        "name": name, "account": account, "profession": profession, "group": group, "guildID": guild,
        "dpsTargets": [[{"dps": dps}]], "defenses": [{"downCount": downs}],
        "buffUptimes": [{"id": 740, "buffData": [{"uptime": might}]},
                        {"id": 1187, "buffData": [{"uptime": quickness}]}],
    }


def report(*, success=True, burned=100.0, players=None):
    """A synthetic dps.report getJson response for Vale Guardian."""
    return {
        "triggerID": 15438, "fightName": "Vale Guardian", "success": success, "duration": "04m 30s 250ms",
        "timeStart": "2024-03-05 20:00:00 +01", "timeEnd": "2024-03-05 20:04:30 +01", "recordedBy": "Alpha",
        "phases": [{"targets": [0]}],
        "targets": [{"name": "Vale Guardian", "healthPercentBurned": burned}],
        "buffMap": {"b740": {"name": "Might", "stacking": True}, "b725": {"name": "Fury", "stacking": False},
                    "b1187": {"name": "Quickness", "stacking": False},
                    "b30328": {"name": "Alacrity", "stacking": False},
                    "b717": {"name": "Protection", "stacking": False}},
        "players": players or [
            player("Alpha", "Alpha.1234", "Firebrand", 3000),
            player("Bravo", "Bravo.5678", "Berserker", 9000, downs=2, might=25.0),
        ],
    }


UPLOADED = {"id": "abc-123", "permalink": "https://dps.report/abc-123", "error": None}


def dps_report(data=None, **options):
    return subject.FakeDpsReport({"abc-123": data or report()}, upload=UPLOADED, **options)


def fields(embed):
    return {f["name"]: f["value"] for f in embed["fields"]}


# --- The report embed ---------------------------------------------------------------------


async def test_report_embed(gamedata):
    sent, db, _ = await subject.upload_logs([subject.log_file()], dps_report())
    [(content, embed)] = sent
    assert content is None
    assert embed["title"] == "DPS Report"
    assert embed["url"] == "https://dps.report/abc-123"
    assert embed["description"] == "Encounter duration: **4** minutes, **30** seconds"
    assert embed["color"] == 0x2ECC71  # green: a kill
    assert embed["author"] == {"name": "Vale Guardian", "icon_url": gamedata["bosses"]["15438"]["icon"]}
    assert embed["timestamp"] == "2024-03-05T19:04:30+00:00"
    assert embed["footer"] == {"text": "Recorded at", "icon_url": "https://cdn/bot.png"}
    values = fields(embed)
    assert values["> **BOSS**"] == "Health: **0%**\n" + "━" * 20
    # Highest DPS first
    assert values["> **PLAYERS**"] == (
        " **Bravo** *(Bravo.5678)* | Downed count: **2**\n **Alpha** *(Alpha.1234)*"
    )
    # Names padded with non-breaking spaces, so Discord keeps the columns
    pad = "\u00a0" * 14
    assert values["> **DPS**"].split("\n") == [
        "`Bravo" + pad + "▀" * 15 + "━" * 5 + "` **9000** DPS | **75%** of group DPS",
        "`Alpha" + pad + "▀" * 5 + "━" * 15 + "` **3000** DPS | **25%** of group DPS",
        "> Group DPS: **12000**",
    ]
    assert "> **BUFFS**" in values


async def test_report_saves_the_encounter_once():
    _, db, _ = await subject.upload_logs([subject.log_file()], dps_report())
    [doc] = db.encounters.docs
    assert {k: v for k, v in doc.items() if k != "_id"} == {
        "boss_id": 15438,
        "start_date": datetime.datetime(2024, 3, 5, 19, tzinfo=UTC),
        "date": datetime.datetime(2024, 3, 5, 19, 4, 30, tzinfo=UTC),
        "players": ["Alpha.1234", "Bravo.5678"],
        "permalink": "https://dps.report/abc-123",
        "success": True,
        "duration": 270,
    }
    # The same fight uploaded again, e.g. by another player
    _, db, _ = await subject.upload_logs([subject.log_file()], dps_report(), encounters=db.encounters.docs)
    assert len(db.encounters.docs) == 1


async def test_report_for_a_wipe():
    sent, _, _ = await subject.upload_logs([subject.log_file()], dps_report(report(success=False, burned=75.0)))
    [(_, embed)] = sent
    assert embed["color"] == 0xE74C3C  # red
    assert fields(embed)["> **BOSS**"] == "Health: **25.0%**\n" + "▀" * 5 + "━" * 15


# --- Uploading ---------------------------------------------------------------------------------


async def test_first_upload_gets_a_dps_report_token():
    service = dps_report()
    _, _, writes = await subject.upload_logs([subject.log_file()], service)
    assert writes == [(1, "set", {"dpsreport_token": "DPS-TOKEN"})]
    assert service.requests == [
        ("GET", DPS_REPORT + "getUserToken", {}),
        ("POST", DPS_REPORT + "uploadContent", {"json": 1, "userToken": "DPS-TOKEN"}),
        ("GET", DPS_REPORT + "getJson", {"id": "abc-123"}),
    ]


async def test_anonymous_upload():
    service = dps_report()
    await subject.upload_logs([subject.log_file()], service, anonymous=True)
    assert service.requests[1] == ("POST", DPS_REPORT + "uploadContent",
                                   {"json": 1, "anonymous": "true", "userToken": "DPS-TOKEN"})


async def test_upload_error():
    service = subject.FakeDpsReport(upload={"error": "Encounter is too short for a useful report"})
    sent, db, _ = await subject.upload_logs([subject.log_file()], service)
    assert sent == [("Error processing your log! :x:", None)]
    assert db.encounters.docs == []


async def test_only_log_files_are_processed():
    service = dps_report()
    sent, _, _ = await subject.upload_logs([subject.log_file("notes.txt"), subject.log_file()], service)
    assert len(sent) == 1


async def test_evtc_command():
    embed = await subject.evtc_command(subject.log_file(), dps_report())
    assert embed["title"] == "DPS Report"
    sent = await subject.evtc_command(subject.log_file("screenshot.png"), dps_report())
    assert sent == ("The attachment seems not to be of a correct filetype.\n"
                    "Allowed file extensions: `.evtc, .zevtc, .zip`")


# --- Autopost -------------------------------------------------------------------------------------

NOTIFICATION = {"_id": "n1", "user_id": 1, "encounter_id": "abc-123", "permalink": "https://dps.report/abc-123",
                "posted": False}


def destination(channel_id=5, guild_ids=()):
    return {"user_id": 1, "channel_id": channel_id, "guild_ids": list(guild_ids), "guild_tags": []}


async def test_autopost_to_each_destination():
    channels = [subject.RecordingChannel(5, 10), subject.RecordingChannel(6, 11)]
    notifications = await subject.run_evtc_autopost(
        [NOTIFICATION], [destination(5), destination(6)], {"abc-123": report()}, channels
    )
    assert [len(c.sent) for c in channels] == [1, 1]
    embed = channels[0].sent[0][1]
    assert embed["title"] == "DPS Report"
    assert embed["footer"]["text"].startswith("Autoposted by example")
    assert notifications[0]["posted"] is True


async def test_autopost_guild_filter():
    # Alpha recorded it while representing GUILD-A
    channels = [subject.RecordingChannel(5, 10), subject.RecordingChannel(6, 11)]
    await subject.run_evtc_autopost(
        [NOTIFICATION], [destination(5, ["GUILD-A"]), destination(6, ["GUILD-C"])], {"abc-123": report()}, channels
    )
    assert [len(c.sent) for c in channels] == [1, 0]


async def test_autopost_respects_permissions():
    # The bot can't embed in 5; the user left the server of 6; 7 is gone
    channels = [subject.RecordingChannel(5, 10, can_embed=False), subject.RecordingChannel(6, 11)]
    await subject.run_evtc_autopost(
        [NOTIFICATION], [destination(5), destination(6), destination(7)], {"abc-123": report()}, channels,
        members={6: []},
    )
    assert [c.sent for c in channels] == [[], []]


async def test_autopost_marks_failures_posted():
    notifications = await subject.run_evtc_autopost([NOTIFICATION], [destination()], {}, [subject.RecordingChannel()])
    assert notifications[0]["posted"] is True


async def test_already_posted_notifications_are_skipped():
    channel = subject.RecordingChannel()
    await subject.run_evtc_autopost([{**NOTIFICATION, "posted": True}], [destination()], {"abc-123": report()},
                                    [channel])
    assert channel.sent == []


# --- Destinations -----------------------------------------------------------------------------------

GUILDS = [{"id": "GUILD-A", "name": "Alpha Guild", "tag": "A"}, {"id": "GUILD-B", "name": "Bravo Guild", "tag": "B"}]
ADDED = ("This channel is now a destination for EVTC logs. Logs uploaded using third-party utilities with your "
         "GW2Bot EVTC API key will be posted here. You can have multiple destinations at the same time. DMs also "
         "work.\nYou can always remove it using ")


async def test_add_destination_for_some_guilds():
    replies, destinations = await subject.evtc_destination_command("add", guilds=GUILDS, choose=["GUILD-A"])
    assert replies[0].startswith("If you wish to use this channel to post only the logs made while representing")
    assert replies[1].startswith(ADDED)
    assert [{k: v for k, v in d.items() if k != "_id"} for d in destinations] == [
        {"user_id": 1, "channel_id": 5, "guild_ids": ["GUILD-A"], "guild_tags": ["A"]},
    ]


async def test_add_destination_for_all_guilds():
    replies, destinations = await subject.evtc_destination_command("add", guilds=GUILDS, choose="next")
    assert replies[1].startswith(ADDED)
    assert destinations[0]["guild_ids"] == []


async def test_add_destination_timed_out():
    _, destinations = await subject.evtc_destination_command("add", guilds=GUILDS)
    assert destinations == []


async def test_add_destination_needs_an_evtc_api_key():
    replies, _ = await subject.evtc_destination_command("add", api_key=False)
    assert replies[0].startswith("You don't have an EVTC API key generated.")


async def test_add_destination_twice():
    replies, _ = await subject.evtc_destination_command("add", destinations=[destination()], guilds=GUILDS)
    assert replies[0].startswith("This channel is already a destination.")


async def test_remove_destinations():
    channel = subject.RecordingChannel(5, 10)
    channel.name = "logs"
    channel.guild.name = "Example Server"
    replies, destinations = await subject.evtc_destination_command(
        "remove", destinations=[destination(5)], channels={5: channel}, choose=[0]
    )
    assert replies == ["** **", "Removed selected destinations."]
    assert destinations == []


async def test_remove_without_destinations():
    replies, _ = await subject.evtc_destination_command("remove")
    assert replies == ["You don't have any autopost destinations yet."]


# --- Fixes -------------------------------------------------------------------------------------------


async def test_later_uploads_use_the_saved_token():
    service = dps_report()
    await subject.upload_logs([subject.log_file()], service, stored={"dpsreport_token": "SAVED"})
    assert service.requests[0] == ("POST", DPS_REPORT + "uploadContent", {"json": 1, "userToken": "SAVED"})


async def test_autopost_footer_names_the_user():
    channel = subject.RecordingChannel()
    await subject.run_evtc_autopost([NOTIFICATION], [destination()], {"abc-123": report()}, [channel])
    assert channel.sent[0][1]["footer"]["text"].startswith("Autoposted by example (1).")


async def test_add_destination_without_guilds():
    replies, destinations = await subject.evtc_destination_command("add", account={"name": "Example.1234"})
    assert replies[0].startswith(ADDED)
    assert destinations[0]["guild_ids"] == []


async def test_remove_an_inaccessible_destination():
    replies, destinations = await subject.evtc_destination_command(
        "remove", destinations=[destination(5)], channels={}, choose=[0]
    )
    assert replies == ["** **", "Removed selected destinations."]
    assert destinations == []
