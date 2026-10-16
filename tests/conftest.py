import json
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "guildwars2"

# The cog is written to live at cogs/guildwars2 inside Toothy and imports
# itself as `cogs.guildwars2`. Point a synthetic `cogs` package at the repo
# root so those imports resolve without a Toothy checkout.
if "cogs" not in sys.modules:
    cogs = types.ModuleType("cogs")
    cogs.__path__ = [str(ROOT)]
    sys.modules["cogs"] = cogs

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
