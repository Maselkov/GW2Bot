"""Server settings: the /server group, and forced account names."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import tasks

from ..i18n import LANGUAGE_NAMES, N_, resolve_language
from .base import GW2Cog
from .guild import guild_name_autocomplete
from .language import AUTOMATIC, language_choices


class Server(GW2Cog):

    @app_commands.guild_only()
    @app_commands.default_permissions(
        manage_guild=True, manage_roles=True, manage_nicknames=True
    )
    class ServerGroup(
        app_commands.Group, name="server", description="Server management commands"
    ):
        pass

    server_group = ServerGroup(guild_only=True)

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)

    async def cog_load(self):
        self.forced_account_names.start()

    async def cog_unload(self):
        self.forced_account_names.cancel()

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
        lang = await self.lang(interaction)
        guild = interaction.guild
        doc = await self.bot.data.guilds.get(guild.id)
        if doc and enabled and doc.get("force_account_names"):
            return await interaction.response.send_message(
                self.t(lang, N_("Forced account names are already enabled"))
            )
        if not enabled:
            await self.bot.data.guilds.update(guild.id, {"force_account_names": False})
            return await interaction.response.send_message(
                self.t(lang, N_("Forced account names disabled"))
            )
        await self.bot.data.guilds.update(guild.id, {"force_account_names": True})
        # Reply first: renaming a big server takes longer than an
        # interaction may wait
        await interaction.response.send_message(content=self.t(lang, N_(
            "Automatic account names enabled. To disable, use "
            "`/server force_account_names enabled:False`\nPlease note that the "
            "bot cannot change nicknames for roles above the bot."
        )))
        await self.force_guild_account_names(guild)

    @server_group.command(name="preview_chat_links")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(enabled="Enable or disable automatic chat link preview")
    async def previewchatlinks(self, interaction: discord.Interaction, enabled: bool):
        """Enable or disable automatic GW2 chat link preview"""
        lang = await self.lang(interaction)
        guild = interaction.guild
        doc = await self.bot.data.guilds.get(interaction.guild.id)
        disabled = doc.get("link_preview_disabled", False)
        if disabled and not enabled:
            return await interaction.response.send_message(
                self.t(lang, N_("Chat link preview is aleady disabled.")), ephemeral=True
            )
        if not disabled and enabled:
            return await interaction.response.send_message(
                self.t(lang, N_("Chat link preview is aleady enabled.")), ephemeral=True
            )
        # The previews are the ChatLinks cog's
        previews = self.bot.get_cog("ChatLinks")
        if not disabled and not enabled:
            await self.bot.data.guilds.update(guild.id, {"link_preview_disabled": True})
            if previews:
                previews.set_previews_enabled(guild.id, False)
            return await interaction.response.send_message(
                self.t(lang, N_("Chat link preview is now disabled.")), ephemeral=True
            )
        if disabled and enabled:
            await self.bot.data.guilds.update(guild.id, {"link_preview_disabled": not enabled})
            if previews:
                previews.set_previews_enabled(guild.id, True)
            return await interaction.response.send_message(
                self.t(lang, N_("Chat link preview is now enabled.")), ephemeral=True
            )

    @server_group.command(name="language")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(language="Automatic follows the server's Discord language")
    @app_commands.choices(language=language_choices())
    async def server_language(self, interaction: discord.Interaction, language: str):
        """Choose the language of the bot's posts in this server"""
        guild = interaction.guild
        if language == AUTOMATIC:
            await self.bot.data.guilds.update(guild.id, {"language": ""}, op="unset")
            text = N_("The bot now posts in this server's Discord language, {language}. "
                      "Its replies to members follow their own language.")
            language = resolve_language(guild.preferred_locale)
        else:
            await self.bot.data.guilds.update(guild.id, {"language": language})
            text = N_("The bot now posts in {language} in this server. "
                      "Its replies to members follow their own language.")
        lang = await self.lang(interaction)
        await interaction.response.send_message(self.t(lang, text, language=LANGUAGE_NAMES[language]))

    @server_group.command(name="sync_now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sync_now(self, interaction: discord.Interaction):
        """Force a sync for any Guildsyncs you have"""
        lang = await self.lang(interaction)
        await interaction.response.send_message(self.t(lang, N_("Syncs scheduled!")))
        guild_sync = self.bot.get_cog("GuildSync")
        if guild_sync:
            await guild_sync.guildsync_now(interaction)

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
        lang = await self.lang(interaction)
        if enabled and not role:
            return await interaction.response.send_message(
                self.t(lang, N_("If enabling, you must specify a role "
                                "to give to members with an API key.")),
                ephemeral=True,
            )
        guild = interaction.guild
        settings = {"key_sync.enabled": enabled}
        if role:
            settings["key_sync.role"] = role.id
        await self.bot.data.guilds.update(guild.id, settings)
        if enabled:
            if not role:
                return await interaction.response.send_message(self.t(lang, N_("Please specify a role.")))
            await interaction.response.send_message(self.t(lang, N_(
                "Key sync enabled. Members with valid API keys "
                "will now be given the selected role"
            )))
            # The role sync is the Keys cog's
            keys = self.bot.get_cog("Keys")
            if keys:
                await keys.key_sync_guild(guild)
            return
        await interaction.response.send_message(self.t(lang, N_("Key sync disabled.")))

    @server_group.command(name="default_guild")
    @app_commands.describe(guild="Guild name")
    @app_commands.autocomplete(guild=guild_name_autocomplete)
    async def guild_default(self, interaction: discord.Interaction, guild: str):
        """Set your default guild for guild commands on this server."""
        lang = await self.lang(interaction)
        await interaction.response.defer()
        results = await self.call_api(f"guild/{guild}")
        await self.bot.data.guilds.update(interaction.guild.id, {"guild_ingame": guild})
        await interaction.followup.send(self.t(lang, N_(
            "Your default guild is now set to {guild} for this "
            "server. All commands from the `guild` command group "
            "invoked without a specified guild will default to "
            "this guild. To reset, simply invoke this command "
            "without specifying a guild"
        ), guild=results["name"]))

    @tasks.loop(minutes=5)
    async def forced_account_names(self):
        cursor = self.bot.data.guilds.find({"force_account_names": True})
        async for doc in cursor:
            try:
                guild = self.bot.get_guild(doc["_id"])
                if not guild:
                    continue
                await self.force_guild_account_names(guild)
            except asyncio.CancelledError:
                return
            except Exception:
                self.log.exception("Couldn't force account names in server %s", doc["_id"])

    @forced_account_names.before_loop
    async def before_forced_account_names_loop(self):
        await self.bot.wait_until_ready()

    async def force_guild_account_names(self, guild):
        if not guild.chunked:
            await guild.chunk()
        users = await self.users_by_id(member.id for member in guild.members)
        for member in guild.members:
            name = (users.get(member.id, {}).get("key") or {}).get("account_name")
            if not name or name.lower() in member.display_name.lower():
                continue
            try:
                await member.edit(nick=name, reason="Force account names - /server")
            except discord.Forbidden:
                # Above the bot's role, or the server's owner
                continue


async def setup(bot):
    await bot.add_cog(Server(bot))
