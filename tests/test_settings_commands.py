"""Server and channel settings commands."""
import subject


async def test_chat_link_previews_can_be_disabled_and_reenabled():
    commands = subject.SettingsCommands()
    assert await commands.run("previewchatlinks", enabled=False) == "Chat link preview is now disabled."
    assert 10 in commands.cog.chatcode_preview_opted_out_guilds
    assert await commands.run("previewchatlinks", enabled=False) == "Chat link preview is aleady disabled."
    assert await commands.run("previewchatlinks", enabled=True) == "Chat link preview is now enabled."
    assert 10 not in commands.cog.chatcode_preview_opted_out_guilds


async def test_disabled_chat_link_previews_survive_a_restart():
    commands = subject.SettingsCommands()
    await commands.run("previewchatlinks", enabled=False)
    commands.start()
    await commands.load()
    assert commands.cog.chatcode_preview_opted_out_guilds == {10}


async def test_force_account_names_already_enabled():
    commands = subject.SettingsCommands()
    first = await commands.run("server_force_account_names", enabled=True)
    assert first.startswith("Automatic account names enabled.")
    assert await commands.run("server_force_account_names", enabled=True) == (
        "Forced account names are already enabled"
    )
    commands.cog.force_guild_account_names.assert_awaited_once()
    assert await commands.run("server_force_account_names", enabled=False) == "Forced account names disabled"
    assert (await commands.guilds.get(10))["force_account_names"] is False


async def test_evtc_channel_follows_the_enabled_option():
    commands = subject.SettingsCommands()
    channel = commands.channel(500)
    reply = await commands.run("evtc_channel", enabled=True, channel=channel, autodelete=True)
    assert reply.startswith("Automatic EVTC processing enabled.")
    # Asking to enable again keeps it enabled (it used to toggle)
    await commands.run("evtc_channel", enabled=True, channel=channel, autodelete=False)
    assert (await commands.channels.get(500))["evtc"] == {"enabled": True, "autodelete": False}
    reply = await commands.run("evtc_channel", enabled=False, channel=channel, autodelete=False)
    assert reply == "Automatic EVTC processing disabled"
    assert (await commands.channels.get(500))["evtc"]["enabled"] is False


# --- EVTC uploads -------------------------------------------------------------


async def test_evtc_uploads_need_an_enabled_channel_in_servers():
    uploads = subject.EvtcUploads()
    assert await uploads.post("log.zevtc") == (False, False)
    await uploads.channels.update(500, {"evtc.enabled": True, "evtc.autodelete": False})
    assert await uploads.post("log.zevtc") == (True, False)
    assert await uploads.post("log.zevtc", channel_id=501) == (False, False)


async def test_evtc_uploads_are_always_processed_in_dms():
    uploads = subject.EvtcUploads()
    assert await uploads.post("log.zevtc", in_guild=False) == (True, False)


async def test_evtc_autodelete():
    uploads = subject.EvtcUploads()
    await uploads.channels.update(500, {"evtc.enabled": True, "evtc.autodelete": True})
    assert await uploads.post("log.evtc") == (True, True)
    # Without Manage Messages the upload is processed but kept
    assert await uploads.post("log.evtc", can_manage=False) == (True, False)


async def test_non_evtc_attachments_are_ignored():
    uploads = subject.EvtcUploads()
    await uploads.channels.update(500, {"evtc.enabled": True})
    assert await uploads.post("screenshot.png") == (False, False)
    assert await uploads.post("screenshot.png", in_guild=False) == (False, False)
