import re

import discord
from discord import app_commands
from discord.app_commands import Choice
from .exceptions import APIError, APIInactiveError


class KeyMixin:

    key_group = app_commands.Group(name="key", description="API key management")

    @key_group.command(name="add")
    @app_commands.describe(
        token="Generate at https://account.arena.net under Applications tab"
    )
    async def key_add(self, interaction: discord.Interaction, token: str):
        """Adds a key and associates it with your discord account"""
        await interaction.response.defer(ephemeral=True)
        doc = await self.bot.database.get(interaction.user, self)
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
        await self.bot.database.set(
            interaction.user, {"key": key_doc, "keys": keys}, self
        )
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
                await self.worldsync_on_member_join(interaction.user)
                await self.guildsync_on_member_join(interaction.user)
                await self.key_sync_user(interaction.user)
                return
            for guild in self.bot.guilds:
                try:
                    if len(guild.members) > 5000:
                        continue
                    if interaction.user not in guild.members:
                        continue
                    member = guild.get_member(interaction.user.id)
                    await self.key_sync_user(member)
                    doc = await self.bot.database.get(guild, self)
                    worldsync = doc.get("worldsync", {})
                    worldsync_enabled = worldsync.get("enabled", False)
                    if worldsync_enabled:
                        await self.worldsync_on_member_join(member)
                    guildsync = doc.get("sync", {})
                    if guildsync.get("on", False) and guildsync.get("setupdone", False):
                        await self.guildsync_on_member_join(member)
                except Exception:
                    pass
        except Exception:
            pass

    async def key_autocomplete(self, interaction: discord.Interaction, current: str):
        doc = await self.bot.database.get(interaction.user, self)
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
        doc = await self.bot.database.get(interaction.user, self)
        keys = doc.get("keys", [])
        key = doc.get("key", {})
        to_keep = []
        if key.get("key") == token:
            key = {}
        for k in keys:
            if k["key"] != token:
                to_keep.append(k)
        if key == key and to_keep == keys:
            return await interaction.followup.send(
                "No keys were removed. Invalid token"
            )
        await self.bot.database.set(
            interaction.user, {"key": key, "keys": to_keep}, self
        )
        await interaction.followup.send("Key removed.")

    @key_group.command(name="info")
    async def key_info(self, interaction: discord.Interaction):
        """Information about your api keys"""
        doc = await self.bot.database.get(interaction.user, self)
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
        doc = await self.bot.database.get(interaction.user, self)
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
        await self.bot.database.set(interaction.user, {"key": k}, self)
        msg = "Swapped to selected key."
        if key["name"]:
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
