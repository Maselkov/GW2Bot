import asyncio
import discord
from discord.ext import tasks
from discord import app_commands
from ..guild import guild_name_autocomplete


class GuildManageMixin:

    @app_commands.guild_only()
    @app_commands.default_permissions(
        manage_guild=True, manage_roles=True, manage_nicknames=True
    )
    class ServerGroup(
        app_commands.Group, name="server", description="Server management commands"
    ):
        pass

    server_group = ServerGroup(guild_only=True)

    @server_group.command(name="force_account_names")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    @app_commands.checks.bot_has_permissions(manage_nicknames=True)
    @app_commands.describe(
        enabled="Enable or disable automatically changing user "
        "nicknames to match in-game account name"
    )
    async def server_force_account_names(
        self, interaction: discord.Interaction, enabled: bool
    ):
        """Automatically change all server member nicknames to in-game names"""
        guild = interaction.guild
        doc = await self.bot.data.guilds.get(guild.id)
        if doc and enabled and doc.get("force_account_names"):
            return await interaction.response.send_message(
                "Forced account names are already enabled"
            )
        if not enabled:
            await self.bot.data.guilds.update(guild.id, {"force_account_names": False})
            return await interaction.response.send_message(
                "Forced account names disabled"
            )
        await self.bot.data.guilds.update(guild.id, {"force_account_names": True})
        await self.force_guild_account_names(guild)
        await interaction.response.send_message(
            content="Automatic account names enabled. To disable, use "
            "`/server forceaccountnames false`\nPlease note that the "
            "bot cannot change nicknames for roles above the bot."
        )

    @server_group.command(name="preview_chat_links")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(enabled="Enable or disable automatic chat link preview")
    async def previewchatlinks(self, interaction: discord.Interaction, enabled: bool):
        """Enable or disable automatic GW2 chat link preview"""
        guild = interaction.guild
        doc = await self.bot.data.guilds.get(interaction.guild.id)
        disabled = doc.get("link_preview_disabled", False)
        if disabled and not enabled:
            return await interaction.response.send_message(
                "Chat link preview is aleady disabled.", ephemeral=True
            )
        if not disabled and enabled:
            return await interaction.response.send_message(
                "Chat link preview is aleady enabled.", ephemeral=True
            )
        if not disabled and not enabled:
            await self.bot.data.guilds.update(guild.id, {"link_preview_disabled": True})
            self.chatcode_preview_opted_out_guilds.add(guild.id)
            return await interaction.response.send_message(
                "Chat link preview is now disabled.", ephemeral=True
            )
        if disabled and enabled:
            await self.bot.data.guilds.update(guild.id, {"link_preview_disabled": not enabled})
            try:
                self.chatcode_preview_opted_out_guilds.remove(guild.id)
            except KeyError:
                pass
            return await interaction.response.send_message(
                "Chat link preview is now enabled.", ephemeral=True
            )

    @server_group.command(name="sync_now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sync_now(self, interaction: discord.Interaction):
        """Force a sync for any Guildsyncs you have"""
        await interaction.response.send_message("Syncs scheduled!")
        await self.guildsync_now(interaction)

    @server_group.command(name="api_key_role")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.describe(
        enabled="Enable or disable giving members with an API key a role",
        role="The role that will be given to members with an API key added",
    )
    async def server_key_sync(
        self, interaction: discord.Interaction, enabled: bool, role: discord.Role = None
    ):
        """A feature to automatically add a role to members that have added an
        API key to the bot."""
        if enabled and not role:
            return await interaction.response.send_message(
                "If enabling, you must specify a role "
                "to give to members with an API key.",
                ephemeral=True,
            )
        guild = interaction.guild
        await self.bot.data.guilds.update(guild.id, {"key_sync.enabled": enabled, "key_sync.role": role.id})
        if enabled:
            if not role:
                return await interaction.response.send_message("Please specify a role.")
            await interaction.response.send_message(
                "Key sync enabled. Members with valid API keys "
                "will now be given the selected role"
            )
            return await self.key_sync_guild(guild)
        await interaction.response.send_message("Key sync disabled.")

    @server_group.command(name="default_guild")
    @app_commands.describe(guild="Guild name")
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_default(self, interaction: discord.Interaction, guild: str):
        """Set your default guild for guild commands on this server."""
        await interaction.response.defer()
        results = await self.call_api(f"guild/{guild}")
        await self.bot.data.guilds.update(interaction.guild.id, {"guild_ingame": guild})
        await interaction.followup.send(
            f"Your default guild is now set to {results['name']} for this "
            "server. All commands from the `guild` command group "
            "invoked without a specified guild will default to "
            "this guild. To reset, simply invoke this command "
            "without specifying a guild"
        )

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

    @key_sync_task.before_loop
    async def before_forced_account_names(self):
        await self.bot.wait_until_ready()

    async def force_guild_account_names(self, guild):
        for member in guild.members:
            try:
                key = await self.fetch_key(member)
                name = key["account_name"]
                if name.lower() not in member.display_name.lower():
                    await member.edit(nick=name, reason="Force account names - /server")
            except Exception:
                pass
