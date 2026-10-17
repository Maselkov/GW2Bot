"""Record GW2 API responses as test fixtures.

Usage:
    GW2_API_KEY=... python scripts/record_gw2_fixtures.py

Writes scrubbed JSON to tests/fixtures/gw2api/. The key is only sent to the
API, never written to disk. Scrubbing:

- account name and id, guild ids, character names (including soulbound
  items' `bound_to`) are replaced with placeholders
- creation timestamps are replaced with a fixed date and the home world with
  another world in the same region
- wallet values, PvP stats, AP, ranks, ages and death counts are randomly
  varied by up to 30%

Before a file is written, it is checked for the real account name, account
id, guild ids, character names and the key; recording aborts if any remain.
Review the diff before committing.
"""
import asyncio
import json
import os
import pathlib
import random
import sys
import urllib.parse

import aiohttp

API = "https://api.guildwars2.com/v2/"
OUT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "gw2api"
)

PUBLIC = [
    "build",
    "worlds?ids=all",
    "items/46762",
    "items?ids=19721,24575,24615,30684",
    "skills/5491",
    "traits/1510",
    "pvp/ranks/1",
    "commerce/prices/19721",
    "wvw/matches?world=11001",
]
AUTHENTICATED = [
    "account",
    "account/wallet",
    "account/achievements",
    "pvp/stats",
    "characters?ids=all",
]
# Keep large list responses small enough to review
LIMITS = {"account/achievements": 50, "characters?ids=all": 2}

FAKE_ACCOUNT = "Example.1234"
FAKE_UUID = "00000000-0000-0000-0000-000000000000"
FAKE_CREATED = "2015-01-01T00:00:00Z"
JITTER = 0.3


class LeakError(Exception):
    pass


class Scrubber:
    def __init__(self, account=None, character_names=(), world_ids=(), rng=None):
        self.rng = rng or random.Random()
        self.guild_ids = {}
        self.character_names = {
            name: f"Character {i + 1}" for i, name in enumerate(character_names)
        }
        self.world_ids = list(world_ids)
        self.secrets = set(character_names)
        if account:
            self.secrets |= {account["name"], account["id"]}
            self.secrets |= set(account.get("guilds", []))
            self.secrets |= set(account.get("guild_leader", []))

    def guild(self, guild_id):
        return self.guild_ids.setdefault(
            guild_id, f"00000000-0000-0000-0000-{len(self.guild_ids):012d}"
        )

    def character(self, name):
        if name not in self.character_names:
            self.secrets.add(name)
            self.character_names[name] = f"Character {len(self.character_names) + 1}"
        return self.character_names[name]

    def jitter(self, value, low=0, high=None):
        if isinstance(value, bool) or not isinstance(value, int) or value == 0:
            return value
        value = round(value * self.rng.uniform(1 - JITTER, 1 + JITTER))
        value = max(low, value)
        return min(high, value) if high is not None else value

    def jitter_all(self, data):
        """Jitter every integer in a nested structure."""
        if isinstance(data, dict):
            return {k: self.jitter_all(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.jitter_all(v) for v in data]
        return self.jitter(data)

    def world(self, world_id):
        region = [w for w in self.world_ids if w // 1000 == world_id // 1000]
        return self.rng.choice(region) if region else world_id

    def unbind(self, data):
        """Replace character names in every `bound_to` field."""
        if isinstance(data, dict):
            for k, v in data.items():
                if k == "bound_to" and isinstance(v, str):
                    data[k] = self.character(v)
                else:
                    self.unbind(v)
        elif isinstance(data, list):
            for v in data:
                self.unbind(v)

    def scrub(self, endpoint, data):
        if endpoint == "account":
            data["id"] = FAKE_UUID
            data["name"] = FAKE_ACCOUNT
            for key in ("guilds", "guild_leader"):
                if key in data:
                    data[key] = [self.guild(g) for g in data[key]]
            if "world" in data:
                data["world"] = self.world(data["world"])
            if "created" in data:
                data["created"] = FAKE_CREATED
            for key in ("age", "daily_ap", "monthly_ap"):
                if key in data:
                    data[key] = self.jitter(data[key])
            if "wvw_rank" in data:
                data["wvw_rank"] = self.jitter(data["wvw_rank"], low=1)
            if "fractal_level" in data:
                data["fractal_level"] = self.jitter(data["fractal_level"], high=100)
        elif endpoint == "account/wallet":
            for entry in data:
                entry["value"] = self.jitter(entry["value"])
        elif endpoint == "pvp/stats":
            rank = data.get("pvp_rank")
            data = self.jitter_all(data)
            if rank is not None:
                data["pvp_rank"] = self.jitter(rank, low=1, high=80)
        elif endpoint.startswith("characters"):
            for character in data:
                character["name"] = self.character(character["name"])
                if character.get("guild"):
                    character["guild"] = self.guild(character["guild"])
                if "created" in character:
                    character["created"] = FAKE_CREATED
                for key in ("age", "deaths"):
                    if key in character:
                        character[key] = self.jitter(character[key])
            self.unbind(data)
        return data

    def check(self, endpoint, text):
        leaked = [s for s in self.secrets if s and s in text]
        if leaked:
            raise LeakError(
                f"{endpoint}: {len(leaked)} personal value(s) survived scrubbing; "
                "nothing was written for this endpoint"
            )


def fixture_name(endpoint):
    path = endpoint.split("?")[0].replace("/", "__")
    if "?" in endpoint:
        path += "__" + endpoint.split("?")[1].replace("=", "-").replace(",", "_")
    return path + ".json"


async def main():
    key = os.environ.get("GW2_API_KEY")
    if not key:
        print("Authenticated endpoints skipped: GW2_API_KEY not set", file=sys.stderr)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "GW2Bot fixture recorder"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as client:

        async def get(endpoint, authenticated):
            # Send the endpoint's own query through params too, so it's
            # combined with the key the same way whatever the client does
            path, _, query = endpoint.partition("?")
            params = dict(urllib.parse.parse_qsl(query))
            if authenticated:
                params["access_token"] = key
            async with client.get(API + path, params=params) as r:
                r.raise_for_status()
                return await r.json()

        world_ids = await get("worlds", False)
        if key:
            scrubber = Scrubber(
                await get("account", True), await get("characters", True), world_ids
            )
            scrubber.secrets.add(key)
        else:
            scrubber = Scrubber(world_ids=world_ids)

        endpoints = [(e, False) for e in PUBLIC]
        if key:
            endpoints += [(e, True) for e in AUTHENTICATED]
        for endpoint, authenticated in endpoints:
            data = await get(endpoint, authenticated)
            if endpoint in LIMITS:
                data = data[: LIMITS[endpoint]]
            data = scrubber.scrub(endpoint, data)
            text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            scrubber.check(endpoint, text)
            out = OUT_DIR / fixture_name(endpoint)
            out.write_text(text, encoding="utf-8")
            print(f"{endpoint} -> {out.relative_to(OUT_DIR.parent.parent.parent)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except LeakError as e:
        sys.exit(f"Aborted: {e}")
