# Background tasks: behaviour checklist

What the old `GuildWars2` cog (`gw2bot/cogs/guildwars2/`) does without anyone running a command: timed loops,
event listeners and persistent buttons. Written from the code as of the misc cog move (#192), before any of it
moves to its own cog.

**How to use it.** Each Phase 6 PR moves one section below. In order:

1. Write the section's **Tests to write** first, against the current code. Known bugs are strict xfails.
2. Move the code. The tests must pass unchanged.
3. Fix bugs, test first.
4. Update the section: what changed, and which tests now cover it.

A behaviour that changes on purpose is called out in the PR. Anything else that changes is a regression.

## Shared facts

- **Start and stop.** `GuildWars2.__init__` starts every loop; `cog_unload` cancels them. Each loop waits for
  `bot.wait_until_ready()` before its first run. `cog_load` registers the two persistent views and loads the chat
  link opt-out cache.
- **Errors stop loops.** `discord.ext.tasks` retries an iteration after network errors (`OSError`,
  `aiohttp.ClientError`, `asyncio.TimeoutError`, gateway errors). **Any other exception stops the loop until the
  bot restarts**, after logging "Unhandled exception in internal background task". `APIError` is a plain
  `Exception`, and so are XML parse errors and `KeyError`. Only the daily notifier has an error handler, which
  restarts it.
- **Swallowed errors.** Many loops wrap each guild or user in `except Exception: pass`. One bad server can't stop
  the loop, but its failures are invisible: nothing is logged.
- **Untracked tasks.** The daily notifier and event reminders start an `asyncio.create_task` per guild or
  reminder and keep no reference. Their exceptions only appear as "Task exception was never retrieved", and the
  tasks can be garbage-collected mid-run.
- **Settings.** Server settings are `bot.data.guilds` documents (`gw2bot.db.settings.SettingsRepo`); user
  settings are `bot.data.users`; the bot's caches are the `bot.data.config` document. Game data caches and the
  guild sync and EVTC collections are in `bot.data.gw2` (`self.db`).

## Summary

| Section | Trigger | Writes | Messages | Worst known issue |
|---|---|---|---|---|
| [Daily notifier](#daily-notifier) | 23:40 UTC daily; dailies refresh every 15 min | `daily.message`, dailies cache | channel posts, pins | `/notifier daily` times out with an error |
| [Event reminders](#event-reminders) | every 10 s | `event_reminders` | DMs | Users with closed DMs are retried forever |
| [Boss notifier](#boss-notifier) | before each world boss | `bossnotifs.message` | channel posts | Failures are silent |
| [Chat link previews](#chat-link-previews) | every message | `statistics.link_previews` | replies | Undecodable links raise in `finally` |
| [News](#news) | every 3 min | `cache.news`, `news.on` | channel posts | Items whose title changes are posted again |
| [Game updates](#game-updates) | every 1 min | `cache.build`, game data caches, `updates` | channel posts | The rebuild runs inside the loop |
| [Gem tracker](#gem-tracker) | every 5 min | `gemtrack` | DMs | Undeliverable users are retried forever |
| [EVTC autopost](#evtc-autopost-and-uploads) | every 5 s; uploads on message | `evtc.notifications`, `encounters` | channel posts | "name#0" in footers |
| [API key role](#api-key-role-and-key) | every 5 min; `/key add` | member roles | — | `/key remove` for legacy users |
| [Forced account names](#forced-account-names) | every 5 min | member nicknames | — | Failures are silent |
| [Guild sync](#guild-sync) | every 60 s; member join | roles, kicks, `guildsyncs` | DMs, prompts | Heavy: a database read per member per minute |

## Daily notifier

`notifiers.py: send_daily_notifs`, `database.py: refresh_dailies, cache_dailies`, `daily.py: daily_embed`.
Set up with `/notifier daily` (channel, categories dropdown, pin, behaviour: none / autodelete / autoedit).

- **Schedule.**
  - `refresh_dailies` runs every 15 minutes and caches today's and tomorrow's rotation in `config.cache.dailies`
    and `cache.dailies_tomorrow`. It logs API errors and anything else, so it never stops.
  - `send_daily_notifs` runs at 23:40 UTC and posts **tomorrow's** dailies, 20 minutes before reset. It refreshes
    the cache first, falling back to the existing cache.
- **For each server** with `daily.on` and a channel, as a separate untracked task:
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
  - The per-server tasks are untracked (see Shared facts).
  - `/notifier daily` waits 60 s for the dropdown, then calls `followup.edit_message` without a message id, which
    fails.
- **Tests.**
  - Existing: rotation, categories and the embed (`test_logic.py`); each behaviour and autopin
    (`test_daily_notifier.py`).
  - To write: missing permissions, and the cache refresh failing.

## Event reminders

`events.py: event_reminder_task, process_reminder, get_time_until_event`, `EventTimerReminderUnsubscribeView`,
`notifiers.py: reminder_event`. Set up with `/reminder event` (event name, minutes before, 0–60).

- **Schedule.** Every 10 s, for each user with `event_reminders`, one untracked task per reminder.
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
  - Users with closed DMs are retried every 10 s, forever.
- **Tests.**
  - Existing: event timing (`test_logic.py`); `/reminder event` for each kind of event, and a boss missing from
    the schedule (`test_event_reminders.py`).
  - To write: when a reminder fires and when it's held back, the DM and its saved fields, and Unsubscribe.

## Boss notifier

`notifiers.py: boss_notifier`. Set up with `/notifier bosses` (channel, behaviour: delete (default) / edit).

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
  - Silent failures: a deleted channel or missing permissions are never logged or turned off.
  - The setup command's choice text says "the previous day's message"; it's the previous boss's message.
  - The "Need permission" message itself fails without send permission, and that's swallowed too.
- **Tests.**
  - Existing: the schedule (`test_logic.py`).
  - To write: a run against fake servers for delete and edit, missing permissions, and a deleted channel.

## Chat link previews

`chatlinks.py: find_chatcodes` (an `on_message` listener), `/server preview_chat_links`.

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
  - If the link can't be decoded, or has an unknown type byte, `link_type` is unset when the `finally` block
    counts it. That raises `UnboundLocalError` out of the listener, so discord.py logs it as an unhandled error.
  - A map link whose POI isn't cached raises `TypeError` (logged).
  - An item link with a skin that isn't cached raises after setting the name to "Unknown" (logged).
- **Tests.**
  - Existing: the opt-out command and its restart cache (`test_settings_commands.py`), skill and trait embeds
    (`test_skills.py`), build images (`test_rendering.py`).
  - To write: one preview per link type, an opted-out server, a bot author, and an undecodable link (xfail).

## News

`notifiers.py: news_checker, check_news, send_news`. Set up with `/notifier news` (channel, optional role).

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
- **Tests.**
  - Existing: the first run posting nothing, new items, filtering, and a non-XML response (`test_notifiers.py`).
  - To write: the role mention, and `Forbidden` turning news off.

## Game updates

`notifiers.py: game_update_checker, game_build_changed, send_update_notifs, update_notification`,
`update_notes.py`, `database.py: rebuild_database`. Set up with `/notifier update` (channel, optional role).

- **Schedule.** Every minute.
- **Behaviour.**
  - **Build check:** reads the build number from `http://assetcdn.101.arenanetworks.com/latest/101`. If it
    differs from `config.cache.build`, it saves it and **rebuilds the game data cache inside the loop**. The
    rebuild sets the bot's status to "Rebuilding API cache" and re-fetches items, achievements, skins, skills and
    more; failures DM the owner. No updates are posted until it's done.
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
  - To write: the build check (changed / unchanged / bad page), sending to servers (mention or none, minor
    posts, text without embed permission), and the rebuild's status and owner DM using a fake API.

## Gem tracker

`notifiers.py: gem_tracker`, `/gem track` (`commerce.py`).

- **Schedule.** Every 5 minutes.
- **Behaviour.** Fetches the price of 400 gems (`commerce.gem_price`). For each user whose `gemtrack` is above
  it, DMs them and clears `gemtrack`.
- **Errors.** Per-user errors are swallowed: an uncached user (`get_user` is `None`) or closed DMs. Those users
  are retried every 5 minutes, forever.
- **Known issues.**
  - *Fixed:* an API error from `gem_price` stopped the loop until restart. It's logged now.
  - Users the bot can't see or DM are never cleared or told.
- **Tests.**
  - Existing: `/gem track` and `gem_price` (`test_commerce.py`); notifying and clearing, and an API error
    (`test_notifiers.py`).
  - To write: closed DMs and users the bot can't see.

## EVTC autopost and uploads

`evtc.py: post_evtc_notifications, on_message, process_evtc, upload_log`. Set up with `/evtc channel`,
`/evtc autopost`, `/evtc api_key`.

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
  - The footer uses `user.discriminator`, so new-style usernames show as "name#0".
  - A user who left the server raises on `permissions_for(None)` (logged, then skipped).
  - `guild.chunk()` runs per destination in the loop.
- **Tests.**
  - Existing: `/evtc api_key` (`test_evtc_api_key.py`), the upload listener's channel and autodelete rules
    (`test_settings_commands.py`).
  - To write: autopost with a fake dps.report covering destinations, the guild filter, the permission rules, and
    marking failures as posted.

## API key role, and /key

`guildmanage.py: key_sync_task, key_sync_guild, key_sync_user, /server api_key_role`, `key.py`.

- **Schedule.**
  - Every 5 minutes, for each server with `key_sync.enabled`: chunks the member list, then gives `key_sync.role`
    to every member with a key and removes it from members without one.
  - `/key add` in a server also runs the role sync and guild sync for that member.
- **Errors.** Swallowed per server. A missing role is skipped. `Forbidden` on a member is skipped.
- **Known issues.**
  - *Fixed:* `/server api_key_role enabled:False` without a role crashed, so key sync couldn't be turned off.
  - *Fixed:* `/key switch` named the previous key, and crashed when no key was active.
  - `/key remove` for a legacy user with only `key` (no `keys` list) says "No keys were removed": the
    `key == key` check is always true.
  - "Valid API key" only means "has a key"; keys aren't re-checked.
  - The role isn't given when a member joins, only on the next 5-minute run.
- **Tests.**
  - Existing: `/server api_key_role` and `/key switch` (`test_server_commands.py`).
  - To write: the role given and taken on a fake server, and `/key add`, `remove` and `info`.

## Forced account names

`notifiers.py: forced_account_names`, `guildmanage.py: force_guild_account_names`,
`/server force_account_names`.

- **Schedule.** Every 5 minutes, for each server with `force_account_names`: every cached member with a key whose
  display name doesn't contain their account name gets that account name as their nickname.
- **Errors.** All swallowed: members without keys, members above the bot's role, missing permissions.
- **Known issues.**
  - Relies on the member lists loaded at startup; unlike key sync, it never chunks a server itself.
  - Enabling runs the rename before replying, so on big servers the interaction can time out.
  - The reply tells people to use `/server forceaccountnames false`; the command is `force_account_names`.
- **Tests.**
  - Existing: "already enabled" (`test_settings_commands.py`).
  - To write: renames, skipped members (no key, name already contained), and errors.

## Guild sync

`guild/sync.py`: `guild_synchronizer`, `run_guildsyncs`, `SyncGuild`, `SyncTarget`, `guildsync_on_member_join`,
`GuildSyncPromptUserConfirmView`, `/guildsync add / edit / toggle / purge / diagnose`, `/server sync_now`.

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
  - The `APIForbidden` error message reads "Key has in-game leader permissions"; it means the key lacks them.
  - `guildsync_consumer`, `schedule_guildsync` and the queue they use are dead code: nothing starts or calls them,
    and the queue is never created.
  - A `print("failed")` is left over.
  - Messages still mention `$guildsync`, the old prefix command.
  - One users-collection read per server member per minute, per server.
- **Tests.**
  - Existing: none.
  - To write:
    - role creation and deletion for tag and ranks;
    - membership with several accounts and ranks, and the role hierarchy limit;
    - the member-join sync;
    - purge: done in #194 (`tests/test_guildsync.py`);
    - the authorization prompt;
    - the sync limit: done (`test_server_commands.py`).

## Order

Least risky first. Each item is one PR.

1. Daily notifier and `/daily`.
2. Event reminders, the boss notifier and `/et`.
3. Chat link previews and `/server preview_chat_links`.
4. News, game updates, the gem tracker and the `/notifier` commands.
5. EVTC.
6. `/key` and the API key role.
7. Guild sync, forced account names and the rest of `/server`.

The guild sync purge issue was the exception, fixed ahead of the order in #194 because it affected live servers.
