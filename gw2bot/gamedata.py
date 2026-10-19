"""Static game data bundled with the bot."""
import json
import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"


def load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def load_gamedata():
    """(gamedata, instabilities) from gamedata.json and instabilities.json."""
    return load("gamedata.json"), load("instabilities.json")
