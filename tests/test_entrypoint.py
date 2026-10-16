"""docker/entrypoint.py: config generation for the container."""
import importlib.util
import json

import pytest

from conftest import ROOT


@pytest.fixture
def entrypoint(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("entrypoint", ROOT / "docker" / "entrypoint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    example = tmp_path / "config-example.json"
    example.write_text(json.dumps({
        "TOKEN": "",
        "PREFIXES": [">"],
        "DATABASE": {"host": "localhost", "port": 27017, "credentials": {}},
    }))
    monkeypatch.setattr(module, "SETTINGS_DIR", str(tmp_path))
    monkeypatch.setattr(module, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(module, "EXTENSIONS_PATH", str(tmp_path / "extensions.json"))
    monkeypatch.setattr(module, "EXAMPLE_PATH", str(example))
    for var in ("DISCORD_TOKEN", "OWNER_ID", "TEST_GUILD", "DEBUG", "PREFIX", "MONGO_HOST",
                "MONGO_PORT", "MONGO_DB", "MONGO_USER", "MONGO_PASSWORD", "MONGO_AUTH_DB"):
        monkeypatch.delenv(var, raising=False)
    return module


def read(path):
    return json.loads(path.read_text())


def test_builds_config_from_env(entrypoint, tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "tok")
    monkeypatch.setenv("OWNER_ID", "123")
    monkeypatch.setenv("DEBUG", "yes")
    monkeypatch.setenv("PREFIX", "!")
    monkeypatch.setenv("MONGO_HOST", "mongo")
    monkeypatch.setenv("MONGO_PORT", "27018")
    monkeypatch.setenv("MONGO_USER", "u")
    entrypoint.build_config()
    config = read(tmp_path / "config.json")
    assert config["TOKEN"] == "tok"
    assert config["OWNER_ID"] == 123
    assert config["DEBUG"] is True
    assert config["PREFIXES"] == ["!"]
    assert config["DATABASE"]["host"] == "mongo"
    assert config["DATABASE"]["port"] == 27018
    assert config["DATABASE"]["credentials"] == {"user": "u"}


def test_env_overrides_existing_config_but_keeps_other_keys(entrypoint, tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({"TOKEN": "old", "CUSTOM": 1}))
    monkeypatch.setenv("DISCORD_TOKEN", "new")
    entrypoint.build_config()
    config = read(tmp_path / "config.json")
    assert config["TOKEN"] == "new"
    assert config["CUSTOM"] == 1


def test_empty_env_vars_are_ignored(entrypoint, tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({"TOKEN": "keep"}))
    monkeypatch.setenv("DISCORD_TOKEN", "")
    entrypoint.build_config()
    assert read(tmp_path / "config.json")["TOKEN"] == "keep"


def test_exits_without_token(entrypoint):
    with pytest.raises(SystemExit):
        entrypoint.build_config()


def test_enables_extensions_without_overriding_choices(entrypoint, tmp_path):
    (tmp_path / "extensions.json").write_text(json.dumps({"cogs.guildwars2": False}))
    entrypoint.enable_extensions()
    assert read(tmp_path / "extensions.json") == {"cogs.guildwars2": False, "cogs.owner": True}
