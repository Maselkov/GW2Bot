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
| `MONGO_DB` | Database name (default `toothy`, for compatibility with data from the Toothy days). |
| `LOG_DIR` | Where `gw2bot.log` is written (default `logs`). |
| `DEBUG` | `true` for debug logging. |

On startup the bot syncs its slash commands with Discord, but only if they changed since the last sync. It stores a hash of the commands in MongoDB to tell. Owner text commands, sent to the bot in a direct message:

- `>sync`: sync slash commands now, for example after commands were synced from somewhere else. `>sync true` syncs them to `TEST_GUILD` only.
- `>reload`: reload the GW2 cog after a code change. Run `>sync` afterwards if its commands changed.

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

GW2Bot used to run as an extension of [Toothy](https://github.com/Maselkov/Toothy). It now runs on its own, and reads the same MongoDB data. Point it at the database Toothy used: set `MONGO_DB` to the `DATABASE.name` from Toothy's `config.json` (`toothy` unless you changed it).

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

Tests don't need Discord. The tests in `tests/test_database.py` run against a real MongoDB, and are skipped unless `MONGO_TEST_URI` is set. Each test creates its own database and drops it afterwards. CI runs them with a MongoDB service.

```bash
docker run -d --rm -p 127.0.0.1:27017:27017 mongo:9
MONGO_TEST_URI=mongodb://localhost:27017 .venv-test/bin/pytest
```

Tests only check inputs and outputs, so they survive a restructure of the code. They never call the cog's mixins directly. Instead they go through the plain functions in `tests/subject.py`. When logic moves, point the matching function in `subject.py` at its new home and the tests stay the same.

Known bugs are marked `xfail(strict=True)`. Fixing one makes its test report XPASS, which fails the run until the marker is removed.

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
