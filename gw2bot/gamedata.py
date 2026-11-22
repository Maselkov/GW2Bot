"""Static game data bundled with the bot."""
import json
import pathlib

from .i18n import N_

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"


def load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def load_gamedata():
    """(gamedata, instabilities) from gamedata.json and instabilities.json."""
    return load("gamedata.json"), load("instabilities.json")


# Item rarities, as the API names them, marked for translation (the game's
# names: see the Item page of each language's wiki)
RARITIES = (
    N_("Junk"), N_("Basic"), N_("Fine"), N_("Masterwork"),
    N_("Rare"), N_("Exotic"), N_("Ascended"), N_("Legendary"),
)

# Attributes, by the API's codes (items' and skills' attributes, buff
# conversions), with the game's names
ATTRIBUTES = {
    "Power": N_("Power"),
    "Precision": N_("Precision"),
    "Toughness": N_("Toughness"),
    "Vitality": N_("Vitality"),
    "Healing": N_("Healing Power"),
    "BoonDuration": N_("Concentration"),
    "ConditionDuration": N_("Expertise"),
    "ConditionDamage": N_("Condition Damage"),
    "CritDamage": N_("Ferocity"),
}

# Weapon types, as the API names them
WEAPONS = {
    "Axe": N_("Axe"), "Dagger": N_("Dagger"), "Mace": N_("Mace"), "Pistol": N_("Pistol"),
    "Scepter": N_("Scepter"), "Sword": N_("Sword"), "Focus": N_("Focus"), "Shield": N_("Shield"),
    "Torch": N_("Torch"), "Warhorn": N_("Warhorn"), "Greatsword": N_("Greatsword"),
    "Hammer": N_("Hammer"), "Longbow": N_("Longbow"), "Rifle": N_("Rifle"),
    "Shortbow": N_("Shortbow"), "Staff": N_("Staff"), "Speargun": N_("Speargun"),
    "Spear": N_("Spear"), "Trident": N_("Trident"),
}

# Crafting disciplines, as the API names them
CRAFTING = {
    "Armorsmith": N_("Armorsmith"), "Artificer": N_("Artificer"), "Chef": N_("Chef"),
    "Huntsman": N_("Huntsman"), "Jeweler": N_("Jeweler"), "Leatherworker": N_("Leatherworker"),
    "Scribe": N_("Scribe"), "Tailor": N_("Tailor"), "Weaponsmith": N_("Weaponsmith"),
}

# Combo fields and finishers, as the API names them in skill facts
COMBO_FIELDS = {
    "Dark": N_("Dark"), "Ethereal": N_("Ethereal"), "Fire": N_("Fire"), "Ice": N_("Ice"),
    "Light": N_("Light"), "Lightning": N_("Lightning"), "Poison": N_("Poison"),
    "Smoke": N_("Smoke"), "Water": N_("Water"),
}
COMBO_FINISHERS = {
    "Blast": N_("Blast"), "Leap": N_("Leap"), "Projectile": N_("Projectile"), "Whirl": N_("Whirl"),
}


def event_timer_names(timers):
    """The names in gamedata.json's event_timers (world bosses, maps and
    their meta event phases), which are shown translated."""
    for subtype in timers["bosses"].values():
        for boss in subtype:
            yield boss["name"]
    for group, maps in timers.items():
        if group == "bosses":
            continue
        for location in maps:
            yield location["name"]
            for phase in location["phases"]:
                if phase["name"]:
                    yield phase["name"]


def killproof_names(killproofs):
    """The area and encounter names in gamedata.json's killproofs (/kp)."""
    for area in killproofs["areas"]:
        yield area["name"]
        for encounter in area["encounters"]:
            yield encounter["name"]
