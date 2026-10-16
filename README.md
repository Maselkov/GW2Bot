# GW2Bot

An extension to [Toothy](https://github.com/Maselkov/Toothy).

[Invite the public bot to your Discord Server!](https://discord.com/api/oauth2/authorize?client_id=310050883100737536&permissions=939879488&scope=bot%20applications.commands)

## How To Run

### With Docker

The Docker image bundles Toothy and GW2Bot, and `docker-compose.yml` runs it alongside MongoDB.

```bash
# Fill in DISCORD_TOKEN and OWNER_ID (see the Discord steps in the Toothy README)
cp .env.example .env

docker compose up -d --build
```

The GW2Bot extension is loaded automatically. Once the bot is online, send it `>sync` in a direct message to register the slash commands.

The container generates `settings/config.json` from the environment variables in `.env`. Settings and logs persist in the `settings` and `logs` volumes, and MongoDB data in `mongo-data`. To pin a different Toothy version, build with `--build-arg TOOTHY_REF=<branch|tag|commit>`.

To use the Guild Wars 2 font in generated images, place `GWTwoFont1p1.ttf` in the `fonts` directory. It is mounted into the container. Without it, the default font is used.

### Manually

First you must install Toothy by following the [Toothy setup instructions](https://github.com/Maselkov/Toothy/blob/master/README.md).

Then clone GW2Bot into the `cogs` directory and install the dependencies:
```bash
# Go to Toothy directory
cd path/to/Toothy

# Clone GW2Bot into the cogs directory
git clone https://github.com/Maselkov/GW2Bot.git ./cogs

# Go to cogs directory
cd cogs

# Activate the Toothy virtual environment you set up with Toothy
source ~/.venvs/toothyenv/bin/activate # POSIX
source ~/.venvs/toothyenv/Scripts/activate # Windows

# Install GW2Bot dependencies
pip install -r requirements.txt
```

Now run Toothy. Note: The default prefix is `>` but you can change this in your `config.json` file.

While Toothy is running, send a direct message via Discord to your Toothy bot to load the GW2Bot extension:
```bash
>load guildwars2
```

After the GW2Bot extension has loaded successfully, send another direct message to your Toothy bot to sync the command tree:
```bash
>sync
```

Now you should be able to use slash commands with your Toothy bot in your Discord server!

## Running Tests

```bash
python -m venv .venv-test
.venv-test/bin/pip install -r requirements-dev.txt
.venv-test/bin/pytest
```

Tests don't need Discord, MongoDB or Toothy. `tests/conftest.py` makes the repository importable as `cogs.guildwars2`.

Tests only check inputs and outputs, so they survive a restructure of the code. They never call the cog's mixins directly. Instead they go through the plain functions in `tests/subject.py`. When logic moves, point the matching function in `subject.py` at its new home and the tests stay the same.

Known bugs are marked `xfail(strict=True)`. Fixing one makes its test report XPASS, which fails the run until the marker is removed.

### Live API tests

`pytest -m live` checks that the live GW2 API still returns the fields the bot reads. Tests that need an API key read it from `GW2_API_KEY` and are skipped without it. They also run nightly in GitHub Actions, using the `GW2_API_KEY` repository secret.

### Recorded API responses

`tests/fixtures/gw2api/` holds real API responses. To refresh them, including the authenticated endpoints:

```bash
GW2_API_KEY=... .venv-test/bin/python scripts/record_gw2_fixtures.py
```

The key is never written to disk. Scrubbing:
- Account names, ids, guild ids and character names (including soulbound items' `bound_to`) are replaced with placeholders.
- Creation dates are replaced with a fixed date, and the home world with another world in the same region.
- Wallet values, PvP stats, AP, ranks, ages and death counts are randomly changed by up to 30%.

The recorder aborts if any real name, id or the key would still be written. Check `git diff tests/fixtures` before committing.

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
