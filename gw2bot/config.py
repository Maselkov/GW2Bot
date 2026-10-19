"""Settings, read from environment variables."""
import dataclasses
import os
import urllib.parse


class ConfigError(Exception):
    pass


def _get(env, name, cast=str, default=None):
    value = env.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return cast(value.strip())
    except ValueError:
        raise ConfigError(f"{name} has an invalid value: {value!r}") from None


def _bool(value):
    return value.lower() in ("1", "true", "yes", "on")


@dataclasses.dataclass(frozen=True)
class Settings:
    token: str
    owner_id: int | None = None
    test_guild: int | None = None
    prefixes: tuple[str, ...] = (">",)
    debug: bool = False
    auto_sync: bool = True
    mongo_uri: str = "mongodb://localhost:27017"
    # GW2Bot's database, and the Toothy-era database it's copied from once
    mongo_db: str = "gw2bot"
    migrate_from_db: str = "toothy"
    log_dir: str = "logs"

    def __post_init__(self):
        if self.mongo_db == self.migrate_from_db:
            raise ConfigError(
                f"MONGO_DB and MIGRATE_FROM_DB are both {self.mongo_db!r}. MONGO_DB is now "
                "GW2Bot's own database (default 'gw2bot'); MIGRATE_FROM_DB names the "
                "Toothy database to copy from (default 'toothy')"
            )

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        token = _get(env, "DISCORD_TOKEN")
        if not token:
            raise ConfigError("DISCORD_TOKEN is not set")
        prefix = _get(env, "PREFIX")
        return cls(
            token=token,
            owner_id=_get(env, "OWNER_ID", int),
            test_guild=_get(env, "TEST_GUILD", int),
            prefixes=(prefix,) if prefix else cls.prefixes,
            debug=_get(env, "DEBUG", _bool, False),
            auto_sync=_get(env, "AUTO_SYNC", _bool, True),
            mongo_uri=_get(env, "MONGO_URI") or _mongo_uri(env),
            mongo_db=_get(env, "MONGO_DB", default=cls.mongo_db),
            migrate_from_db=_get(env, "MIGRATE_FROM_DB", default=cls.migrate_from_db),
            log_dir=_get(env, "LOG_DIR", default=cls.log_dir),
        )


def _mongo_uri(env):
    host = _get(env, "MONGO_HOST", default="localhost")
    port = _get(env, "MONGO_PORT", int, 27017)
    user = _get(env, "MONGO_USER")
    password = _get(env, "MONGO_PASSWORD")
    uri = "mongodb://"
    if user and password:
        uri += "{}:{}@".format(urllib.parse.quote_plus(user), urllib.parse.quote_plus(password))
    uri += f"{host}:{port}"
    if user and password:
        uri += "/" + (_get(env, "MONGO_AUTH_DB") or "admin")
    return uri
