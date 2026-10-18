"""Record public GW2 API responses as test fixtures.

Usage:
    python scripts/record_gw2_fixtures.py

Writes JSON to tests/fixtures/gw2api/. Only public endpoints are recorded:
the repository is public, so tests needing account data (account, wallet,
characters, ...) use synthetic data written in the test instead.
"""
import asyncio
import json
import pathlib

import aiohttp

API = "https://api.guildwars2.com/v2/"
OUT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "gw2api"
)

ENDPOINTS = [
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


def fixture_name(endpoint):
    path = endpoint.split("?")[0].replace("/", "__")
    if "?" in endpoint:
        path += "__" + endpoint.split("?")[1].replace("=", "-").replace(",", "_")
    return path + ".json"


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "GW2Bot fixture recorder"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as client:
        for endpoint in ENDPOINTS:
            async with client.get(API + endpoint) as r:
                r.raise_for_status()
                data = await r.json()
            out = OUT_DIR / fixture_name(endpoint)
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{endpoint} -> {out.relative_to(OUT_DIR.parent.parent.parent)}")


if __name__ == "__main__":
    asyncio.run(main())
