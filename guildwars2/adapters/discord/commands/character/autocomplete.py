from typing import Any, cast
import asyncio
import datetime

import discord
from discord.app_commands import Choice
from discord.ext import commands
from .. import with_cog


@with_cog()
async def character_autocomplete(cog, interaction: discord.Interaction, current: str):
    """Autocomplete character names using cached list per account."""
    if not cog:
        return []
    try:
        key_doc = await cog.container.keys_service.get_key_for_user(
            interaction.user, required_scopes=["characters"], cog=cog
        )
    except Exception:
        return []

    account_key = key_doc["account_name"].replace(".", "_")

    async def cache_characters():
        try:
            character_list = await cog.container.api.get(
                "characters", key=key_doc["key"]
            )
        except Exception:
            return {"last_update": datetime.datetime.utcnow(), "characters": []}
        c = {"last_update": datetime.datetime.utcnow(), "characters": character_list}
        await cog.bot.database.set(
            interaction.user, {f"character_cache.{account_key}": c}, cog
        )
        return c

    doc = await cog.bot.database.get(interaction.user, cog)
    cache = doc.get("character_cache", {}).get(account_key, {}) if doc else {}
    if not cache:
        cache = await cache_characters()
    elif cache["last_update"] < datetime.datetime.utcnow() - datetime.timedelta(days=3):
        asyncio.create_task(cache_characters())
    character_list = cache.get("characters", [])
    current_l = (current or "").lower()
    return [Choice(name=c, value=c) for c in character_list if current_l in c.lower()][
        :25
    ]
