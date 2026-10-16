"""Container entrypoint for Toothy + GW2Bot.

Builds settings/config.json from environment variables (layered over an
existing config.json, or Toothy's example config on first run), makes sure
the GW2Bot extension is enabled, then hands off to Toothy's run.py.
"""
import json
import os
import sys

SETTINGS_DIR = "/app/settings"
CONFIG_PATH = os.path.join(SETTINGS_DIR, "config.json")
EXTENSIONS_PATH = os.path.join(SETTINGS_DIR, "extensions.json")
# Kept outside settings/ since a mounted volume would hide it
EXAMPLE_PATH = "/app/config-example.json"


def env(name, cast=str):
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return cast(value)


def env_bool(value):
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, encoding="utf-8", mode="w") as f:
        json.dump(data, f, indent=4, sort_keys=True)


def build_config():
    if os.path.exists(CONFIG_PATH):
        config = load_json(CONFIG_PATH)
    else:
        config = load_json(EXAMPLE_PATH)

    db = config.setdefault("DATABASE", {})
    credentials = db.setdefault("credentials", {})
    overrides = [
        (config, "TOKEN", env("DISCORD_TOKEN")),
        (config, "OWNER_ID", env("OWNER_ID", int)),
        (config, "TEST_GUILD", env("TEST_GUILD", int)),
        (config, "DEBUG", env("DEBUG", env_bool)),
        (db, "host", env("MONGO_HOST")),
        (db, "port", env("MONGO_PORT", int)),
        (db, "name", env("MONGO_DB")),
        (credentials, "user", env("MONGO_USER")),
        (credentials, "pass", env("MONGO_PASSWORD")),
        (credentials, "authentication_db", env("MONGO_AUTH_DB")),
    ]
    for target, key, value in overrides:
        if value is not None:
            target[key] = value
    prefix = env("PREFIX")
    if prefix is not None:
        config["PREFIXES"] = [prefix]

    if not config.get("TOKEN"):
        sys.exit("No Discord token configured. Set DISCORD_TOKEN or provide "
                 "settings/config.json.")
    write_json(CONFIG_PATH, config)


def enable_extensions():
    extensions = {}
    if os.path.exists(EXTENSIONS_PATH):
        extensions = load_json(EXTENSIONS_PATH)
    extensions.setdefault("cogs.owner", True)
    extensions.setdefault("cogs.guildwars2", True)
    write_json(EXTENSIONS_PATH, extensions)


def main():
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    build_config()
    enable_extensions()
    os.chdir("/app")
    os.execvp(sys.executable, [sys.executable, "run.py"])


if __name__ == "__main__":
    main()
