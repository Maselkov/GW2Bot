import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "gw2bot" / "data"

sys.path.insert(0, str(ROOT / "tests"))


def load_json(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def gamedata():
    return load_json("gamedata.json")


@pytest.fixture(scope="session")
def instabilities():
    return load_json("instabilities.json")
