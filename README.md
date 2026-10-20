# GW2Bot

A Guild Wars 2 Discord bot.

[Invite the public bot to your Discord Server!](https://discord.com/api/oauth2/authorize?client_id=310050883100737536&permissions=939879488&scope=bot%20applications.commands)

## How To Run

GW2Bot needs a Discord bot token and a MongoDB server, version 4.4 or newer. In the [Discord Developer Portal](https://discord.com/developers/applications), enable the **Server Members** and **Message Content** privileged intents for your bot.

Configuration is read from environment variables:

| Variable | |
|---|---|
| `DISCORD_TOKEN` | Required. The bot token. |
| `OWNER_ID` | Your Discord user ID, for owner-only commands like `>sync`. |
| `TEST_GUILD` | Server ID that `>sync true` syncs commands to. |
| `PREFIX` | Prefix for owner text commands (default `>`). |
| `AUTO_SYNC` | Sync slash commands on startup when they changed (default `true`). Set to `false` when running a local copy with the production token, so it can't overwrite production's commands. |
| `MONGO_URI` | Full MongoDB connection string. When set, the `MONGO_HOST`/`PORT`/`USER`/`PASSWORD`/`AUTH_DB` variables are ignored. |
| `MONGO_HOST`, `MONGO_PORT` | Default `localhost:27017`. |
| `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_AUTH_DB` | Optional credentials. The auth database defaults to `admin`. |
| `MONGO_DB` | GW2Bot's database (default `gw2bot`). |
| `MIGRATE_FROM_DB` | The Toothy-era database to copy data from on first start (default `toothy`). It must differ from `MONGO_DB`. |
| `LOG_DIR` | Where `gw2bot.log` is written (default `logs`). |
| `DEBUG` | `true` for debug logging. |

On startup the bot syncs its slash commands with Discord, but only if they changed since the last sync. It stores a hash of the commands in MongoDB to tell. Owner text commands, sent to the bot in a direct message:

- `>sync`: sync slash commands now, for example after commands were synced from somewhere else. `>sync true` syncs them to `TEST_GUILD` only.
- `>reload <cog>`: reload one cog after a code change, e.g. `>reload keys` (the module names in `gw2bot/cogs/`). Run `>sync` afterwards if its commands changed.

### With Docker

`docker-compose.yml` runs the bot alongside MongoDB.

```bash
# Fill in DISCORD_TOKEN and OWNER_ID
cp .env.example .env

docker compose up -d --build
```

Logs persist in the `logs` volume, and MongoDB data in `mongo-data`.

To use the Guild Wars 2 font in generated images, place `GWTwoFont1p1.ttf` in the `fonts` directory. It is mounted into the container. Without it, the default font is used.

### Manually

Requires Python 3.15.

```bash
git clone https://github.com/Maselkov/GW2Bot.git
cd GW2Bot
python -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/pip install --no-deps .

DISCORD_TOKEN=... OWNER_ID=... .venv/bin/gw2bot
```

To use the Guild Wars 2 font, place `GWTwoFont1p1.ttf` in the directory you run the bot from.

### Moving from Toothy

GW2Bot used to run as an extension of [Toothy](https://github.com/Maselkov/Toothy), and stored its data in Toothy's database: settings inside Toothy's shared `users`/`guilds`/`channels` documents, and its own collections under a `gw2.` prefix.

It now has a database of its own. On its first start, the bot copies everything it uses from the Toothy database (`MIGRATE_FROM_DB`, `toothy` unless you changed `DATABASE.name` in Toothy's `config.json`) into `MONGO_DB`, with plain collection names: `users`, `guilds`, `channels`, `config`, `items`, `guildsyncs`, and so on. Indexes are copied too. Collections left over from removed features (boss kills, WvW worlds and population) stay in the old database. The copy is recorded in the new database's `state` collection, so it happens once. A failed copy stops the bot from starting, and the next start tries again.

The Toothy database is only ever read. To roll back, run the previous version, which still uses it. Anything changed since the copy is lost from the rollback's point of view. If you then upgrade again, re-copy so the new database isn't stale:

```bash
python -m gw2bot.db.migrate --dry-run   # what would be copied
python -m gw2bot.db.migrate --force     # copy again over the existing copy
```

The command reads the same `MONGO_*` and `MIGRATE_FROM_DB` settings as the bot. Once you're confident in the new database, the Toothy database can be dropped by hand.

## Code Layout

```
gw2bot/
  __main__.py, config.py   entry point; settings from environment variables
  bot.py                   the bot: startup, the cache defaults, command sync, error messages
  owner.py                 owner text commands (>sync, >reload, >emojis)
  cogs/                    one cog per feature, each loaded as an extension
    base.py                GW2Cog: what every cog shares
    account.py, characters.py, guildsync.py, ...
  gw2api/                  the GW2 API client (retries, rate limits, errors)
  db/                      MongoDB: settings repositories, indexes, the Toothy migration
  keys.py, emojis.py, errors.py, builds.py, gamedata.py
                           services the cogs share: users' API keys, emojis,
                           API error messages, build templates, game data
  utils/                   small helpers (chat formatting, searches, wiki links, ...)
  data/                    game data the bot ships with (bosses, timers, ...)
docs/background-tasks.md   what each loop and listener does, its known issues and tests
```

Each feature is a cog in `gw2bot/cogs/`, a subclass of `GW2Cog` with an `async def setup(bot)`. The bot loads every module there except `base.py`, so a new feature is a new module. `GW2Cog` gives a cog:

- the API (`call_api`, `call_multiple`);
- users' keys (`fetch_key`);
- the game data cache (`self.db`, `fetch_item`);
- emojis and the item search across an account;
- `run_in_background` for work a loop doesn't wait for;
- `users_by_id` for reading many users' settings in one query.

Cogs that run loops start them in `cog_load` and cancel them in `cog_unload`, so `>reload` restarts them.

A slash command group has to live in one cog. So where a command belongs to another cog's group, for example `/server preview_chat_links`, it calls the owning cog through `bot.get_cog(...)`.

## Dependencies

`pyproject.toml` lists the dependencies; `requirements.txt` (runtime) and `requirements-dev.txt` (runtime plus test tools) pin them with hashes. The Docker image, CI and the commands above install from the pins, so every build gets the same versions.

After changing dependencies in `pyproject.toml`, or to upgrade, regenerate the pins (needs Docker):

```bash
scripts/lock.sh                            # re-lock, keeping current versions
scripts/lock.sh --upgrade                  # upgrade everything
scripts/lock.sh --upgrade-package pillow   # upgrade one package
```

Commit both files. The Dependency audit workflow checks the pins for known vulnerabilities daily.

## Running Tests

```bash
python -m venv .venv-test
.venv-test/bin/pip install --require-hashes -r requirements-dev.txt
.venv-test/bin/pip install --no-deps -e .
.venv-test/bin/pytest
```

Tests don't need Discord. The tests that use the `mongo` fixture (the database layer, the Toothy migration and the command tree check) run against a real MongoDB, and are skipped unless `MONGO_TEST_URI` is set. Each test creates its own database and drops it afterwards. CI runs them with a MongoDB service.

```bash
docker run -d --rm -p 127.0.0.1:27017:27017 mongo:9
MONGO_TEST_URI=mongodb://localhost:27017 .venv-test/bin/pytest
```

Tests only check inputs and outputs, so they survive a restructure of the code. They don't call cogs directly; they go through the plain functions in `tests/subject.py`, which run a command, a loop or a listener and return what it sent and wrote. When logic moves, point the matching function in `subject.py` at its new home and the tests stay the same.

The stand-ins those functions use are in `tests/fakes/`:

- `bot.py`: the bot, the clock, and `run_command`.
- `http.py`: the GW2 API and other sites.
- `db.py`: MongoDB collections and settings, with Mongo-style queries.
- `servers.py`: Discord servers, roles, members and channels that record what the bot does to them.

Background tasks are tested one run at a time, through the loop's coroutine, with these fakes.

Known bugs are marked `xfail(strict=True)`. Fixing one makes its test report XPASS, which fails the run until the marker is removed.

CI also runs `ruff check`, set up in `pyproject.toml` to catch mistakes such as unused imports, undefined names and asyncio tasks nobody keeps, not style. Run it before pushing:

```bash
.venv-test/bin/ruff check
```

### Live API tests

`pytest -m live` checks that the live GW2 API still returns the fields the bot reads. Tests that need an API key read it from `GW2_API_KEY` and are skipped without it. They also run nightly in GitHub Actions, using the `GW2_API_KEY` repository secret.

### Recorded API responses

`tests/fixtures/gw2api/` holds real responses from public endpoints (items, skills, prices, WvW matches, ...). To refresh them:

```bash
.venv-test/bin/python scripts/record_gw2_fixtures.py
```

The repository is public, so data from a real account is never committed, not even scrubbed. Tests that need account-shaped data (account, wallet, characters, ...) build synthetic data in the test. `tests/test_fixtures.py` fails if a fixture doesn't come from one of the recorder's public endpoints.

## Feature List

* [Persistent storage of API keys](https://i.imgur.com/m82tUfW.png)
* [Search your account for items](https://i.imgur.com/xt1K62h.png)
* [Automatic game update notifications](https://i.imgur.com/Knq0KYd.png)
* [Legendary Insight count](https://i.imgur.com/XCPA4F4.png)
* [Weekly raid progression table](https://i.imgur.com/JLXRcfe.png)

### Character Stuff:

* [Character info](https://i.imgur.com/V2H4xKb.png)
* [Character list](https://i.imgur.com/jjR5rk9.png)
* [Character gear](https://i.imgur.com/ebRQAVy.png)

### PvP Stuff:

* [Account Stats](https://i.imgur.com/GYouG2j.png)
* [General profession stats](https://i.imgur.com/sptENJA.png)
* [Specific profession stats!](https://i.imgur.com/NQwM9Sx.png)

### Misc

* [Account info](https://i.imgur.com/FXev4g6.png)
* [Skill info](https://i.imgur.com/Qp7H3KO.png)
* [WvW info](https://i.imgur.com/vCetQbN.png)
* [Achievement info](https://i.imgur.com/EZWaLDZ.png)
* [Wallet commands](https://i.imgur.com/qbxsbHQ.png)
* [Guild commands](https://i.imgur.com/qBBG8CF.png) - courtesy of [@n1tr0-5urf3r](https://github.com/n1tr0-5urf3r)
* [Current TP transactions](https://i.imgur.com/UXD6MEf.png) - courtesy of [@n1tr0-5urf3r](https://github.com/n1tr0-5urf3r)
* [Dailies](https://i.imgur.com/RTc0NAa.png)
* [Wiki search](https://i.imgur.com/Uc7j0eb.png)
* [Gem price](https://i.imgur.com/3oWPYOX.png)
* [Event timer](https://i.imgur.com/h4xrOAE.png)

... and more! You can see all available commands on [the GW2Bot website.](https://gw2bot.info/commands)


## Licensed Works Used
[gw2-fotm-instabilities](https://github.com/Invisi/gw2-fotm-instabilities) by [@Invisi](https://github.com/Invisi) which is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
