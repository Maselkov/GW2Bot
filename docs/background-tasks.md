# Background tasks: behaviour checklist

What GW2Bot does without anyone running a command: timed loops, event listeners and persistent buttons. Written
from the old `GuildWars2` cog as of the misc cog move (#192), and kept up to date as each section moved to its own
cog in Phase 6. The old cog is gone now; each section names the cog that owns it.

**How it was used.** Each Phase 6 PR moved one section below. In order:

1. Write the section's **Tests to write** first, against the current code. Known bugs are strict xfails.
2. Move the code. The tests must pass unchanged.
3. Fix bugs, test first.
4. Update the section: what changed, and which tests now cover it.

A behaviour that changes on purpose is called out in the PR. Anything else that changes is a regression.

## Shared facts

- **Start and stop.** Each cog starts its loops in `cog_load` and cancels them in `cog_unload`, so `>reload`
  restarts them. Each loop waits for `bot.wait_until_ready()` before its first run. The `Events` and `GuildSync`
  cogs register their persistent views in `cog_load`; `ChatLinks` loads its opt-out set there.
- **Errors stop loops.** `discord.ext.tasks` retries an iteration after network errors (`OSError`,
  `aiohttp.ClientError`, `asyncio.TimeoutError`, gateway errors). **Any other exception stops the loop until the
  bot restarts**, after logging "Unhandled exception in internal background task". `APIError` is a plain
  `Exception`, and so are XML parse errors and `KeyError`. Only the daily notifier has an error handler, which
  restarts it.
- **Errors per server.** Loops catch each server's or user's errors, so one bad server can't stop the loop, and log
  them with the server's id. (*Fixed:* most used to `except Exception: pass`, so failures were invisible.)
- **Background work.** Work a loop doesn't wait for goes through `GW2Cog.run_in_background`, which keeps the task
  until it's done and logs what it raises. (*Fixed:* the daily notifier and event reminders used bare
  `asyncio.create_task`, whose errors showed only as "Task exception was never retrieved".)
- **Users' settings in bulk.** Syncs over a server's members read their settings in one query
  (`GW2Cog.users_by_id`), not one per member.
- **Settings.** Server settings are `bot.data.guilds` documents (`gw2bot.db.settings.SettingsRepo`); user
  settings are `bot.data.users`; the bot's caches are the `bot.data.config` document. Game data caches and the
  guild sync and EVTC collections are in `bot.data.gw2` (`self.db`).

## Summary

| Section | Trigger | Writes | Messages | Worst known issue |
|---|---|---|---|---|
| [Daily notifier](#daily-notifier) (moved) | 23:40 UTC daily; dailies refresh every 15 min | `daily.message`, dailies cache | channel posts, pins | Permission problems only show in the channel |
| [Event reminders](#event-reminders) (moved) | every 10 s | `event_reminders` | DMs | Reminders saved by index can overwrite each other |
| [Boss notifier](#boss-notifier) (moved) | before each world boss | `bossnotifs.message` | channel posts | A deleted channel is skipped, not turned off |
| [Chat link previews](#chat-link-previews) (moved) | every message | `statistics.link_previews` | replies | Uncached POIs show nothing |
| [News](#news) (moved) | every 3 min | `cache.news`, `news.on` | channel posts | Items whose title changes are posted again |
| [Game updates](#game-updates) (moved) | every 1 min | `cache.build`, game data caches, `updates` | channel posts | The rebuild runs inside the loop |
| [Gem tracker](#gem-tracker) (moved) | every 5 min | `gemtrack` | DMs | — |
| [EVTC autopost](#evtc-autopost-and-uploads) (moved) | every 5 s; uploads on message | `evtc.notifications`, `encounters` | channel posts | `guild.chunk()` per destination |
| [API key role](#api-key-role-and-key) (moved) | every 5 min; joins; `/key add` | member roles | — | Keys aren't re-checked |
| [Forced account names](#forced-account-names) (moved) | every 5 min | member nicknames | — | Doesn't chunk servers itself |
| [Guild sync](#guild-sync) (moved) | every 60 s; member join | roles, kicks, `guildsyncs` | DMs, prompts | A full sync of every server every minute |

## Daily notifier

**Moved** to `gw2bot/cogs/daily.py` (`Daily`): `send_daily_notifs`, `refresh_dailies`, `cache_dailies`, `/daily`
and `daily_embed`. The cog starts its loops in `cog_load`. Set up with `/notifier daily` (channel, categories
dropdown, pin, behaviour: none / autodelete / autoedit), in the `Notifiers` cog; it gets its example notification
from the `Daily` cog.

- **Schedule.**
  - `refresh_dailies` runs every 15 minutes and caches today's and tomorrow's rotation in `config.cache.dailies`
    and `cache.dailies_tomorrow`. It logs API errors and anything else, so it never stops.
  - `send_daily_notifs` runs at 23:40 UTC and posts **tomorrow's** dailies, 20 minutes before reset. It refreshes
    the cache first, falling back to the existing cache.
- **For each server** with `daily.on` and a channel, in the background (`run_in_background`):
  - **Skip:** if the channel is gone or the bot can't send there. Without embed permission it posts "Need
    permission to embed links in order to send daily notifs!".
  - **The post:** title "Dailies", timestamp tomorrow 00:00 UTC, the daily-achievement thumbnail, and the saved
    categories.
  - **Autoedit:** edits the message in `daily.message`; if that fails, posts a new one.
  - **Autodelete:** posts a new message, then deletes the previous one.
  - **New message:** saves its id to `daily.message`.
  - **Autopin:** pins, deletes the bot's "pinned a message" notice, and unpins the previous message.
- **Errors.** The loop's error handler logs and restarts it. Each server's task swallows its own errors.
- **Known issues.**
  - *Fixed:* autopin pinned the previous message instead of a newly posted one, so it only worked with autoedit.
  - *Fixed:* the per-server tasks were untracked, so their errors were lost.
  - *Fixed:* `/notifier daily` failed when the dropdown timed out (`followup.edit_message` without a message id).
  - *Fixed:* `/daily`'s timestamp was a naive `utcnow()`, which discord.py reads as local time.
- **Tests.**
  - Existing: rotation, categories and the embed (`test_logic.py`); each behaviour, autopin, permissions and the
    cache refresh (`test_daily_notifier.py`); `/daily` and `/notifier daily` (`test_daily.py`).

## Event reminders

**Moved** to `gw2bot/cogs/events.py` (`Events`): `event_reminder_task`, `process_reminder`,
`get_time_until_event`, `EventTimerReminderUnsubscribeView` (registered in `cog_load`), and the `/reminder` group
with `/reminder event` (event name, minutes before, 0–60).

- **Schedule.** Every 10 s, for each user with `event_reminders`, one background task per reminder.
- **Behaviour.**
  - **When:** the reminder fires once the event is less than `time + 30` seconds away, and not within
    `time + 120` s of the last reminder.
  - **The DM:** deletes the previous reminder DM, then sends "Event reminder: {name} will begin <relative
    time>" with an Unsubscribe button.
  - **Saves** `last_reminded` and `last_message` to `event_reminders.{i}`.
- **Unsubscribe button.** It's persistent (`custom_id et:unsubscribe`) and works after restarts. It pulls the
  reminder whose `last_message` is this message, and deletes the DM if one was removed.
- **Errors.** Per-user errors are swallowed. A DM that fails to send is skipped and retried 10 s later.
- **Known issues.**
  - *Fixed:* a boss reminder whose name isn't in the schedule froze the whole bot, because
    `get_time_until_event` searched forever without awaiting. It now returns None, and the reminder is skipped.
  - *Fixed:* SotO events couldn't be reminded. `reminder_event` now searches every map event group.
  - Reminders saved by index (`event_reminders.{i}`) can overwrite the wrong one if the list changed meanwhile
    (an unsubscribe from another reminder's DM).
  - *Fixed:* users with closed DMs were retried every 10 s until the event; that spawn now counts as reminded.
- **Tests.**
  - Existing: event timing (`test_logic.py`); `/reminder event`, a boss missing from the schedule, when a
    reminder fires or is held back, the DM and its saved fields, and Unsubscribe (`test_event_reminders.py`).

## Boss notifier

**Moved** to `gw2bot/cogs/events.py` (`Events`): `boss_notifier`. Set up with `/notifier bosses` (channel,
behaviour: delete (default) / edit), in the `Notifiers` cog. *Fixed:* `enabled:False` with a channel enabled it.

- **Schedule.** Every 5 minutes, but each run sleeps until the next world boss spawns plus 1 s. In practice it
  posts once per boss slot.
- **For each server** with `bossnotifs.on` and a channel:
  - **The post:** an embed of the next two bosses (`schedule_embed(2)`).
  - **Edit:** edits `bossnotifs.message`.
  - **Delete (or a failed edit):** posts a new message, saves its id, and deletes the previous one.
  - **No embed permission** (`Forbidden`): posts "Need permission to embed links in order to send boss notifs!"
    every time.
- **Errors.** Swallowed per server, with nothing logged.
- **Known issues.**
  - *Fixed:* in edit mode, a deleted message stopped the server's boss notifications for good. A new message is
    posted instead.
  - *Fixed:* failures were silent. Errors are logged, and a channel it can't post in at all turns the notifier
    off, like news. A deleted channel is still skipped every slot.
  - The setup command's choice text says "the previous day's message"; it's the previous boss's message.
  - The "Need permission" message itself fails without send permission, and that's swallowed too.
- **Tests.**
  - Existing: the schedule (`test_logic.py`); delete and edit modes, a deleted message, missing embed
    permission, and deleted channels (`test_event_reminders.py`).

## Chat link previews

**Moved** to `gw2bot/cogs/chatlinks.py` (`ChatLinks`): `find_chatcodes` (an `on_message` listener) and the
opt-out set, loaded in `cog_load`. `/server preview_chat_links` (in `Server`) updates it through
`set_previews_enabled()`.

- **Trigger.** Any message containing a chat link (`[&...]`), from a human, in a server that hasn't opted out.
  Opt-outs are cached in memory, loaded at startup from `link_preview_disabled`.
- **Behaviour.**
  - **Supported links:** items (with skin and upgrades), map links (POIs), skills, traits, recipes, wardrobe
    skins, outfits and build templates (rendered image). Coins, NPC text, PvP games, users and WvW objectives are
    ignored.
  - **The reply** quotes the message when the bot can read history. Its footer explains how admins opt out.
  - **Counting:** increments `statistics.link_previews.<type>` for every link, even ignored or failed ones.
- **Errors.** Logged with `log.exception`.
- **Known issues.**
  - *Fixed:* an undecodable link or an unknown type byte raised `UnboundLocalError` from the counting `finally`.
    Such links are ignored now.
  - *Fixed:* an item link with an uncached skin raised instead of showing "Unknown".
  - *Fixed:* errors were logged with `log.exception(exc_info=e)`, which itself raised, so they escaped unlogged.
  - A map link whose POI isn't cached shows nothing (the error is logged).
- **Tests.**
  - Existing: the opt-out command and its restart cache (`test_settings_commands.py`), skill and trait embeds
    (`test_skills.py`), build images (`test_rendering.py`), and a preview per link type, opt-outs, bots, invalid
    links and uncached data (`test_chat_links.py`).
  - To write: a build template link end to end.

## News

**Moved** to `gw2bot/cogs/notifiers.py` (`Notifiers`): `news_checker`, `check_news`, `send_news`. Set up with
`/notifier news` (channel, optional role).

- **Schedule.** Every 3 minutes.
- **Behaviour.**
  - **Feed:** fetches `https://www.guildwars2.com/en/feed/` and posts items whose titles aren't in
    `config.cache.news`, then saves the current titles. The first run, with an empty cache, posts nothing.
  - **Per server** with `news.on`: posts each new item as an embed, mentioning `news.role` if it still exists.
    Streaming schedules and community showcases are filtered out (`news.filter` defaults to on; no command sets
    it).
  - **No permission** (`Forbidden`): turns `news.on` off. Other errors are logged.
- **Known issues.**
  - *Fixed:* a feed response that isn't XML (an error or challenge page) stopped the loop. It's logged now.
  - Items whose title changes are posted again.
  - *Fixed:* `/notifier news enabled:False` with a channel enabled it.
- **Tests.**
  - Existing: the first run posting nothing, new items, filtering, the role mention, `Forbidden` turning news off,
    and a non-XML response (`test_notifiers.py`); `/notifier news` (`test_notifier_commands.py`).

## Game updates

**Moved** to `gw2bot/cogs/notifiers.py` (`Notifiers`): `game_update_checker`, `game_build_changed`,
`send_update_notifs`, `update_notification`; the parser is `gw2bot/utils/update_notes.py`. The rebuild is the
`Cache` cog's (`gw2bot/cogs/cache.py: rebuild_database`), called through `bot.get_cog("Cache")`. Set up with
`/notifier update` (channel, optional role).

- **Schedule.** Every minute.
- **Behaviour.**
  - **Build check:** reads the build number from `http://assetcdn.101.arenanetworks.com/latest/101`. If it
    differs from `config.cache.build`, it saves it and **rebuilds the game data cache inside the loop**. The
    rebuild sets the bot's status to "Rebuilding API cache" and re-fetches items, achievements, skins, skills and
    more; failures DM the owner. No updates are posted until it's done. *Fixed:* the last batch of points of
    interest was never saved, and a failure with the owner uncached aborted the rebuild with the status stuck.
    Tested in `test_cache.py`.
  - **Update notes:** reads the forum's release-notes feed and topic, tracking posts per thread in
    `gw2.updates`. The first post is a major update and mentions `updates.mention`. Later posts are hotfixes,
    with no mention. If the forum is blocked, the RSS copy is used.
  - **Posting:** sends "Guild Wars 2 has just updated!" with the embed to each server with `updates.on`, or the
    text alone without embed permission.
- **Errors.**
  - Posting failures are logged per server.
  - `update_notification` failures are logged.
  - *Fixed:* a missing config document or an unexpected build page stopped the loop. It's logged now.
- **Known issues.**
  - Legacy `everyone` / `here` mentions are patched at send time ("TODO").
  - The rebuild runs inside the loop, so a slow rebuild delays update notes.
  - The rebuild's `bot.available` flag isn't read anywhere.
- **Tests.**
  - Existing: notes parsing and which posts to send (`test_update_notes.py`, 18 tests); a bad build page or
    missing config (`test_notifiers.py`).
    The build check, sending to servers (mention, hotfixes, text without embed permission) are covered too.

## Gem tracker

**Moved** to `gw2bot/cogs/notifiers.py` (`Notifiers`): `gem_tracker`. Set up with `/gem track` (`commerce.py`).

- **Schedule.** Every 5 minutes.
- **Behaviour.** Fetches the price of 400 gems (`commerce.gem_price`). For each user whose `gemtrack` is above
  it, DMs them and clears `gemtrack`.
- **Errors.** Per-user errors are swallowed: an uncached user (`get_user` is `None`) or closed DMs. Those users
  are retried every 5 minutes, forever.
- **Known issues.**
  - *Fixed:* an API error from `gem_price` stopped the loop until restart. It's logged now.
  - *Fixed:* users the bot couldn't see or DM were retried every 5 minutes forever; tracking stops for them.
- **Tests.**
  - Existing: `/gem track` and `gem_price` (`test_commerce.py`); notifying and clearing, and an API error
    (`test_notifiers.py`).
    Users it can't DM are kept and retried (`test_notifiers.py`).

## EVTC autopost and uploads

**Moved** to `gw2bot/cogs/evtc.py` (`Evtc`): `post_evtc_notifications` (started in `cog_load`), `on_message`,
`process_evtc`, `upload_log`. Set up with `/evtc_automation channel`, `/evtc_automation autopost` and
`/evtc_automation api_key`. The `evtc.*` collections the EVTC API writes are unchanged.

- **Uploads (listener).**
  - **Which messages:** a message with an `.evtc`, `.zevtc` or `.zip` attachment, in DMs or in channels with
    `evtc.enabled`.
  - **Processing:** uploads to dps.report and saves the encounter to `gw2.encounters`, which `/bosses` links
    to. Replies with an embed, or "Error processing your log! :x:".
  - **Autodelete:** deletes the message if `evtc.autodelete` is on and the bot can manage messages.
- **Autopost (loop).**
  - **Schedule:** every 5 s, for each `evtc.notifications` document with `posted: False`. These are written by
    the external EVTC API.
  - **Posting:** builds the embed and posts it to each of the user's `evtc.destinations`. The bot and the user
    must both be allowed to embed links, send messages and use external emojis there. If the destination has
    `guild_ids`, the recording player's guild must be one of them.
  - **Always marks the notification posted**, even after a failure, so nothing is retried.
- **Errors.** Logged.
- **Known issues.**
  - *Fixed:* a saved dps.report user token was never used, so later uploads weren't linked to the user's account.
  - *Fixed:* autopost footers showed "name#0" for new-style usernames.
  - *Fixed:* adding a destination crashed for an account in no guild; removing one crashed on a channel the bot
    can't see.
  - *Fixed:* messages named commands that don't exist.
  - *Fixed:* a user who left the destination's server was skipped with a logged traceback; now quietly.
  - `guild.chunk()` runs per destination in the loop.
- **Tests.**
  - Existing: `/evtc_automation api_key` (`test_evtc_api_key.py`), the upload listener's channel and autodelete
    rules (`test_settings_commands.py`), and the report embed, encounter saving, uploads, `/evtc`, autopost and
    destinations (`test_evtc.py`).

## API key role, and /key

**Moved** to `gw2bot/cogs/keys.py` (`Keys`): `/key`, `key_sync_task` (started in `cog_load`), `key_sync_guild`,
`key_sync_user` and an `on_member_join` listener. `/server api_key_role` (in `Server`) asks the `Keys` cog to sync;
`/key add` in a server asks the `GuildSync` cog to sync the member.

- **Schedule.**
  - Every 5 minutes, for each server with `key_sync.enabled`: chunks the member list, then gives `key_sync.role`
    to every member with a key and removes it from members without one.
  - `/key add` in a server also runs the role sync and guild sync for that member.
- **Errors.** Swallowed per server. A missing role is skipped. `Forbidden` on a member is skipped.
- **Known issues.**
  - *Fixed:* `/server api_key_role enabled:False` without a role crashed, so key sync couldn't be turned off.
  - *Fixed:* `/key switch` named the previous key, and crashed when no key was active.
  - *Fixed:* `/key remove` couldn't remove a key saved before the keys list existed, and removing the active key
    left none active.
  - *Fixed:* the role wasn't given when a member joined, only on the next 5-minute run.
  - "Valid API key" only means "has a key"; keys aren't re-checked.
- **Tests.**
  - Existing: `/key add`, `remove`, `switch` and `info`, the autocomplete, the role sync and member joins
    (`test_keys.py`), and `/server api_key_role` (`test_server_commands.py`).

## Forced account names

**Moved** to `gw2bot/cogs/server.py` (`Server`): `forced_account_names` (started in `cog_load`),
`force_guild_account_names` and the `/server` group.

- **Schedule.** Every 5 minutes, for each server with `force_account_names`: every cached member with a key whose
  display name doesn't contain their account name gets that account name as their nickname.
- **Errors.** Members without keys and members the bot can't rename (`Forbidden`) are skipped; other errors are
  logged per server. Members' settings are read in one query per server.
- **Known issues.**
  - Relies on the member lists loaded at startup; unlike key sync, it never chunks a server itself.
  - *Fixed:* enabling renamed everyone before replying, so on big servers the interaction could time out; the reply
    named a command that doesn't exist.
- **Tests.**
  - Existing: "already enabled" (`test_settings_commands.py`); enabling, renames and skipped members
    (`test_guildsync_commands.py`).

## Guild sync

**Moved** to `gw2bot/cogs/guildsync.py` (`GuildSync`): `guild_synchronizer` (started in `cog_load`),
`run_guildsyncs`, `SyncGuild`, `SyncTarget`, `guildsync_on_member_join`, `GuildSyncPromptUserConfirmView`
(registered in `cog_load`), `/guildsync add / edit / toggle / purge / diagnose`. `/server sync_now` (in `Server`)
asks it to sync.

- **Schedule.**
  - Every 60 s, for each server with `guildsync.enabled`, a full sync with a 200 s timeout.
  - When a member joins, a sync for that member.
  - `/key add` in a server runs it for the user.
- **A sync,** per guild sync document in `gw2.guildsyncs` (up to 8 per server):
  - **Tag role:** with the tag enabled, creates the tag role if it's missing. With it disabled, deletes it.
  - **Rank roles:** with ranks enabled, fetches `guild/{id}/ranks`, creates a role per rank that lacks one, and
    deletes roles for ranks that no longer exist. With ranks disabled, deletes the rank roles.
  - **Members:** fetches `guild/{id}/members`. For each server member, compares all their accounts (every stored
    key) with the guild's members:
    - gives the tag role to members of the guild;
    - gives the highest rank's role, if it's below the bot's top role;
    - removes other rank roles;
    - removes the tag role from non-members.
  - **Errors** are saved to the sync document (`error`) for `/guildsync diagnose`.
- **Purge** (`guildsync.purge`): after the syncs, kicks members who are in none of the synced guilds, have no
  roles, and joined more than 48 hours ago.
- **Authorization prompt.** When someone other than a guild leader adds a sync, the leader gets a DM with
  persistent buttons. Accepting checks their key's leader access and adds the sync.
- **Errors.** Exceptions per sync are logged. Role, kick and timeout errors are swallowed. The loop swallows each
  server's errors silently.
- **Known issues.**
  - *Fixed in #194:* purge kicked everyone without roles when a sync couldn't read its guild's members, or when
    no syncs were configured. The original guild sync guarded against this; Guildsync 2.0 lost the guard. Since
    discord.py 2.0 a `TypeError` stopped the purge before it kicked anyone, and `00d2453` fixed that error,
    turning the purge back on. It now runs only when every sync read its members.
  - *Fixed:* the limit check allowed 9 syncs instead of 8.
  - *Fixed:* `/guildsync diagnose` checked only a user's first key, and passed users without keys.
  - *Fixed:* `/guildsync edit` "Change API key" never asked for a missing key.
  - *Fixed:* answering an expired authorization prompt crashed.
  - *Fixed:* stale text: "name#0", `$guildsync`, reactions, and "Key has in-game leader permissions" for a key
    without them. The dead `guildsync_consumer` queue and a leftover `print` are gone.
  - *Fixed:* one users read per member per minute, per server; now one query per server.
- **Tests.**
  - Existing: the purge (`test_guildsync.py`), roles and membership (`test_guildsync_roles.py`), the commands and
    the authorization prompt (`test_guildsync_commands.py`), and the sync limit (`test_server_commands.py`).

## Order

Least risky first. Each item is one PR.

1. Daily notifier and `/daily`.
2. Event reminders, the boss notifier and `/et`.
3. Chat link previews and `/server preview_chat_links`.
4. News, game updates, the gem tracker and the `/notifier` commands.
5. EVTC.
6. The game data cache: `>database` and `rebuild_database` (done: `gw2bot/cogs/cache.py`; `>emojis` moved to
   `gw2bot/owner.py`).
7. `/key` and the API key role (done: `gw2bot/cogs/keys.py`).
8. Guild sync, forced account names and the rest of `/server` (done: `gw2bot/cogs/guildsync.py` and
   `gw2bot/cogs/server.py`). The old `gw2bot/cogs/guildwars2/` package is removed.

The guild sync purge issue was the exception, fixed ahead of the order in #194 because it affected live servers.
