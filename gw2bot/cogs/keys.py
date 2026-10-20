"""API keys: /key add, remove, switch and info, and the role servers give to
members with a key (/server api_key_role)."""
import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks

from ..gw2api.errors import APIError, APIInactiveError
from .base import GW2Cog


class Keys(GW2Cog):

    key_group = app_commands.Group(name="key", description="API key management")

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)

    async def cog_load(self):
        self.key_sync_task.start()

    async def cog_unload(self):
        self.key_sync_task.cancel()

    @key_group.command(name="add")
    @app_commands.describe(
        token="Generate at https://account.arena.net under Applications tab"
    )
    async def key_add(self, interaction: discord.Interaction, token: str):
        """Adds a key and associates it with your discord account"""
        await interaction.response.defer(ephemeral=True)
        doc = await self.bot.data.users.get(interaction.user.id)
        try:
            endpoints = ["tokeninfo", "account"]
            token_info, acc = await self.call_multiple(endpoints, key=token)
        except APIInactiveError:
            return await interaction.followup.send(
                "The API is currently down. " "Try again later. "
            )
        except APIError:
            return await interaction.followup.send("The key is invalid.")
        key_doc = {
            "key": token,
            "account_name": acc["name"],
            "name": token_info["name"],
            "permissions": token_info["permissions"],
        }
        # at this point we know the key is valid
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys and key:
            # user already had a key but it isn't in keys
            # (existing user) so add it
            keys.append(key)
        if key_doc["key"] in [k["key"] for k in keys]:
            return await interaction.followup.send(
                "You have already added this key before."
            )
        if len(keys) >= 15:
            return await interaction.followup.send(
                "You've reached the maximum limit of "
                "15 API keys, please remove one before adding "
                "another"
            )
        keys.append(key_doc)
        await self.bot.data.users.update(interaction.user.id, {"key": key_doc, "keys": keys})
        if len(keys) > 1:
            output = (
                "Your key was verified and "
                "added to your list of keys, you can swap between "
                "them at any time using /key switch."
            )
        else:
            output = "Your key was verified and " "associated with your account."
        all_permissions = (
            "account",
            "builds",
            "characters",
            "guilds",
            "inventories",
            "progression",
            "pvp",
            "tradingpost",
            "unlocks",
            "wallet",
        )
        missing = [x for x in all_permissions if x not in key_doc["permissions"]]
        if missing:
            output += (
                "\nPlease note that your API key doesn't have the "
                "following permissions checked: "
                f"```{', '.join(missing)}```\nSome commands "
                "will not work. Consider adding a new key with "
                "those permissions checked."
            )

        await interaction.followup.send(output)
        try:
            if interaction.guild:
                # Guild sync is still the old cog's
                guild_sync = self.bot.get_cog("GuildWars2")
                if guild_sync:
                    await guild_sync.guildsync_on_member_join(interaction.user)
                await self.key_sync_user(interaction.user)
                return
            # Disabled for now while chunking is further investigated
            # for guild in self.bot.guilds:
            #     try:
            #         if len(guild.members) > 5000:
            #             continue
            #         if interaction.user not in guild.members:
            #             continue
            #         member = guild.get_member(interaction.user.id)
            #         await self.key_sync_user(member)
            #         doc = await self.bot.data.guilds.get(guild.id)
            #         guildsync = doc.get("sync", {})
            #         if guildsync.get("on", False) and guildsync.get("setupdone", False):
            #             await self.guildsync_on_member_join(member)
            #     except Exception:
            #         pass
        except Exception:
            pass

    async def key_autocomplete(self, interaction: discord.Interaction, current: str):
        doc = await self.bot.data.users.get(interaction.user.id)
        current = current.lower()
        choices = []
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys and key:
            keys.append(key)
        for key in keys:
            token_name = f"{key['account_name']} - {key['name']}"
            choices.append(Choice(name=token_name, value=key["key"]))
        return [choice for choice in choices if current in choice.name.lower()]

    @key_group.command(name="remove")
    @app_commands.describe(token="The API key to remove from your account")
    @app_commands.autocomplete(token=key_autocomplete)
    async def key_remove(self, interaction: discord.Interaction, token: str):
        """Remove selected keys from the bot"""
        await interaction.response.defer(ephemeral=True)
        doc = await self.bot.data.users.get(interaction.user.id)
        keys = doc.get("keys", [])
        active = doc.get("key", {})
        to_keep = [k for k in keys if k["key"] != token]
        removed_active = active.get("key") == token
        if not removed_active and to_keep == keys:
            return await interaction.followup.send(
                "No keys were removed. Invalid token"
            )
        message = "Key removed."
        if removed_active:
            # Keep a key active while there are any left
            active = to_keep[0] if to_keep else {}
            if active:
                name = active["account_name"]
                if active.get("name"):
                    name += " - " + active["name"]
                message += f" Your active key is now {name}."
        await self.bot.data.users.update(interaction.user.id, {"key": active, "keys": to_keep})
        await interaction.followup.send(message)

    @key_group.command(name="info")
    async def key_info(self, interaction: discord.Interaction):
        """Information about your api keys"""
        doc = await self.bot.data.users.get(interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys and not key:
            return await interaction.followup.send(
                "You have no keys added, you can add one with /key add."
            )
        embed = await self.display_keys(
            interaction, doc, display_active=True, show_tokens=True, reveal_tokens=True
        )
        await interaction.followup.send(embed=embed)

    @key_group.command(name="switch")
    @app_commands.autocomplete(token=key_autocomplete)
    async def key_switch(self, interaction: discord.Interaction, token: str):
        """Swaps between multiple stored API keys."""
        doc = await self.bot.data.users.get(interaction.user.id)
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        if not keys:
            return await interaction.response.send_message(
                "You need to add additional API keys first using /key " "add first.",
                ephemeral=True,
            )
        if key.get("key") == token:
            return await interaction.response.send_message(
                "That key is currently active.", ephemeral=True
            )
        for k in keys:
            if k["key"] == token:
                break
        else:
            return await interaction.response.send_message(
                "That key is not in your account.", ephemeral=True
            )
        await self.bot.data.users.update(interaction.user.id, {"key": k})
        msg = "Swapped to selected key."
        if k["name"]:
            msg += " Name : `{}`".format(k["name"])
        await interaction.response.send_message(msg, ephemeral=True)

    async def display_keys(
        self,
        interaction: discord.Interaction,
        doc,
        *,
        display_active=False,
        display_permissions=True,
        show_tokens=False,
        reveal_tokens=False,
    ):
        def get_value(key):
            lines = []
            if display_permissions:
                lines.append("Permissions: " + ", ".join(key["permissions"]))
            if show_tokens:
                token = key["key"]
                if not reveal_tokens:
                    token = token[:7] + re.sub("[a-zA-Z0-9]", r"\*", token[8:])
                else:
                    token = f"||{token}||"
                lines.append(token)
            return "\n".join(lines)

        keys = doc.get("keys", [])
        embed = discord.Embed(
            title="Your keys", color=await self.get_embed_color(interaction)
        )
        embed.set_author(
            name=interaction.user.name, icon_url=interaction.user.display_avatar.url
        )
        if display_active:
            active_key = doc.get("key", {})
            if active_key:
                name = "**Active key**: {}".format(active_key["account_name"])
                token_name = active_key["name"]
                if token_name:
                    name += " - " + token_name
                embed.add_field(name=name, value=get_value(active_key))
        for counter, key in enumerate(keys, start=1):
            name = "**{}**: {}".format(counter, key["account_name"])
            token_name = key["name"]
            if token_name:
                name += " - " + token_name
            embed.add_field(name=name, value=get_value(key), inline=False)
        embed.set_footer(
            text=self.bot.user.name, icon_url=self.bot.user.display_avatar.url
        )
        return embed

    @tasks.loop(minutes=5)
    async def key_sync_task(self):
        async for doc in self.bot.data.guilds.find({"key_sync.enabled": True}):
            try:
                guild = self.bot.get_guild(doc["_id"])
                role = guild.get_role(doc["key_sync"]["role"])
                if not role:
                    continue
                await self.key_sync_guild(guild, role)
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    async def key_sync_guild(self, guild: discord.Guild, role=None):
        if not role:
            doc = await self.bot.data.guilds.get(guild.id)
            enabled = doc.get("key_sync", {}).get("enabled")
            if not enabled:
                return
            role = guild.get_role(doc["key_sync"]["role"])
        if not role:
            return
        doc = await self.bot.data.guilds.get(guild.id)
        role = guild.get_role(doc["key_sync"]["role"])
        if not role:
            return
        if not guild.chunked:
            await guild.chunk()
        for member in guild.members:
            await self.key_sync_user(member, role)

    async def key_sync_user(self, member, role=None):
        guild = member.guild
        if not guild.me.guild_permissions.manage_roles:
            return
        if not role:
            doc = await self.bot.data.guilds.get(guild.id)
            enabled = doc.get("key_sync", {}).get("enabled")
            if not enabled:
                return
            role = guild.get_role(doc["key_sync"]["role"])
        if not role:
            return
        user_doc = await self.bot.data.users.get(member.id)
        has_key = False
        if user_doc.get("key", {}).get("key"):
            has_key = True
        try:
            if has_key:
                if role not in member.roles:
                    await member.add_roles(role, reason="/server api_key_role")
            else:
                if role in member.roles:
                    await member.remove_roles(
                        role,
                        reason="/server api_key_role is enabled. Member "
                        "lacks a valid API key.",
                    )
        except discord.Forbidden:
            return

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Give the API key role right away, not on the next run."""
        if member.bot:
            return
        await self.key_sync_user(member)

    @key_sync_task.before_loop
    async def before_key_sync_task(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Keys(bot))
