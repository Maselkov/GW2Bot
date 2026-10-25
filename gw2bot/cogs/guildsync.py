"""Guild sync: in-game guild ranks and membership as Discord roles, the
optional purge of members in no synced guild, and /guildsync."""
from __future__ import annotations

import asyncio
import collections
import logging
from datetime import datetime

import discord
from bson import ObjectId
from bson.errors import InvalidId
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks

from gw2bot.utils.db import prepare_search

from ..gw2api.errors import APIError, APIForbidden, APIInvalidKey, APIKeyError, APINotFound
from .base import GW2Cog

PROMPT_EMOJIS = ["✅", "❌"]
GUILDSYNC_LIMIT = 8

# GUILDSYNC SCHEMA
#        guild_info = {
#            "enabled": {"ranks" : Bool, "tag" : Bool},
#            "name": str - guild name
#            "tag": str - guild tag,
#            "rank_roles": dict - mapping of ranks to role ids
#            "gid": str - in game guild id
#            "tag_role": int - role id of the tag role
#            "guild_id" : int - discord guild id
#            "key" : api key
#        }


class ConfirmPurgeView(discord.ui.View):

    def __init__(self):
        super().__init__()
        self.value = None

    @discord.ui.button(emoji="✅", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            "Confirmed. Enabling purge.", ephemeral=True
        )
        self.value = True
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Cancelling", ephemeral=True)
        self.value = False
        self.stop()


class GuildSyncPromptUserConfirmView(discord.ui.View):

    def __init__(self, cog):
        self.cog = cog
        super().__init__(timeout=None)

    async def handle_answer(self, interaction: discord.Interaction, answer):
        query = {"message_id": interaction.message.id}
        doc = await self.cog.db.guildsync_prompts.find_one(query)
        if not doc:
            # Prompts expire after three days
            return await interaction.response.edit_message(
                content="This request has expired.", view=None, embed=None
            )
        if not answer:
            await self.cog.db.guildsync_prompts.delete_one(query)
            return await interaction.response.edit_message(
                content="Noted, request rejected.\nNote that only "
                "admins can send guildsync requests - if you're being "
                "harassed then it is recommended to report them or to leave "
                "the server.",
                view=None,
                embed=None,
            )
        await interaction.response.defer(ephemeral=True)
        try:
            key = await self.cog.fetch_key(interaction.user, scopes=["guilds"])
            key = key["key"]
        except APIKeyError:
            return await interaction.followup.send(
                content="It seems like your key is invalid. Try switching "
                "your key and then try again."
            )
        in_game_guild_id = doc["guildsync_id"]
        is_leader = await self.cog.verify_leader_permissions(key, in_game_guild_id)
        if not is_leader:
            return await interaction.followup.send(
                content="It seems like your key does not have the necessary "
                "in-game permissions. Try switching your key, then try "
                "again by pressing Confirm"
            )
        guild = self.cog.bot.get_guild(doc["guild_id"])
        if not guild:
            return await interaction.followup.send(
                content="It seems like the server no longer exists"
            )
        requesting_user = await self.cog.bot.get_or_fetch_user(doc["requester_id"])
        if not requesting_user:
            return await interaction.followup.send(
                content="It seems like the requesting user no " "longer exists"
            )
        await self.cog.guildsync_success(
            guild,
            in_game_guild_id,
            key=key,
            destination=requesting_user,
            options=doc["options"],
            extra_message="User {0.name} has accepted your "
            "request for Guildsync authorization in {1.name}. "
            "Guild: {2}".format(interaction.user, guild, doc["options"]["name"]),
        )
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            content="Guildsync successfully enabled! Thank you.", ephemeral=True
        )
        await self.cog.db.guildsync_prompts.delete_one(query)

    @discord.ui.button(
        style=discord.ButtonStyle.green,
        emoji="✅",
        label="Confirm",
        custom_id="guildsync:confirm",
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        return await self.handle_answer(interaction, True)

    @discord.ui.button(
        style=discord.ButtonStyle.red,
        emoji="❌",
        label="Deny",
        custom_id="guildsync:deny",
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        return await self.handle_answer(interaction, False)


class GuildSync(GW2Cog):

    @app_commands.guild_only()
    @app_commands.default_permissions(
        manage_guild=True, manage_roles=True, kick_members=True
    )
    class GuildsyncGroup(
        app_commands.Group,
        name="guildsync",
        description="Sync your in-game guild roster with server roles",
    ):
        pass

    guildsync_group = GuildsyncGroup(guild_only=True)

    def __init__(self, bot):
        super().__init__(bot)
        self.log = logging.getLogger(__name__)
        # One sync of a server at a time, so two never create the same roles
        self.sync_locks = collections.defaultdict(asyncio.Lock)

    async def cog_load(self):
        # Authorization prompts' buttons keep working across restarts
        self.bot.add_view(GuildSyncPromptUserConfirmView(self))
        self.guild_synchronizer.start()

    async def cog_unload(self):
        self.guild_synchronizer.cancel()

    class SyncGuild:

        def __init__(self, cog, doc, guild) -> None:
            self.doc_id = doc["_id"]
            self.guild = guild
            self.cog = cog
            self.ranks_to_role_ids = doc["rank_roles"]
            self.roles = {}
            # Reverse hashmap for performance
            self.role_ids_to_ranks = {}
            self.id = doc["gid"]
            self.key = doc["key"]
            self.tag_role_id = doc["tag_role"]
            self.tag_role = None
            self.tag_enabled = doc["enabled"]["tag"]
            self.guild_name = f"{doc['name']} [{doc['tag']}]"
            self.ranks_enabled = doc["enabled"]["ranks"]
            self.base_ep = f"guild/{self.id}/"
            self.ranks = None
            self.members = None
            self.error = None
            self.last_error = doc.get("error")
            self.create_roles = guild.me.guild_permissions.manage_roles
            self.delete_roles = self.create_roles

        async def fetch_members(self):
            ep = self.base_ep + "members"
            results = await self.cog.call_api(endpoint=ep, key=self.key)
            self.members = {r["name"]: r["rank"] for r in results}

        async def save(self, *, ranks=False, tag_role=False, edited=False, error=False):
            update = {}
            if ranks:
                roles = {rank: role.id for rank, role in self.roles.items()}
                update["rank_roles"] = roles
            if tag_role:
                update["tag_role"] = self.tag_role_id
            if edited:
                update["key"] = self.key
                update["enabled.ranks"] = self.ranks_enabled
                update["enabled.tag"] = self.tag_enabled
            if error:
                update["error"] = self.error
            await self.cog.db.guildsyncs.update_one(
                {"_id": self.doc_id}, {"$set": update}
            )

        async def delete(self):
            await self.cog.db.guildsyncs.delete_one({"_id": self.doc_id})
            for role_id in self.ranks_to_role_ids.values():
                await self.safe_role_delete(self.guild.get_role(role_id))
            await self.safe_role_delete(self.guild.get_role(self.tag_role_id))

        async def create_role(self, rank=None):
            if not self.create_roles:
                return
            if rank:
                name = rank
            else:
                name = self.guild_name
            coro = self.guild.create_role(
                name=name,
                reason="/guildsync",
                color=discord.Color(self.cog.embed_color),
            )
            try:
                return await asyncio.wait_for(coro, timeout=5)
            except discord.Forbidden:
                self.error = "Bot lacks permission to create roles."
                self.create_roles = False
            except asyncio.TimeoutError:
                self.create_roles = False
            except discord.HTTPException:
                pass

        async def safe_role_delete(self, role):
            if not self.delete_roles:
                return
            if role:
                try:
                    coro = role.delete(
                        reason="/guildsync - role removed " "or renamed in-game"
                    )
                    await asyncio.wait_for(coro, timeout=5)
                    return True
                except (discord.Forbidden, asyncio.TimeoutError):
                    self.delete_roles = False
                except discord.HTTPException:
                    pass
                return False
            return True

        async def synchronize_roles(self):
            if self.tag_enabled:
                self.tag_role = self.guild.get_role(self.tag_role_id)
                if not self.tag_role:
                    role = await self.create_role()
                    if role:
                        self.tag_role = role
                        self.tag_role_id = role.id
                        await self.save(tag_role=True)
            else:
                if self.tag_role_id:
                    role = self.guild.get_role(self.tag_role_id)
                    if await self.safe_role_delete(role):
                        self.tag_role = None
                        self.tag_role_id = None
                        await self.save(tag_role=True)
            if self.ranks_enabled:
                ep = f"guild/{self.id}/ranks"
                try:
                    ranks = await self.cog.call_api(ep, key=self.key)
                except APIForbidden:
                    self.error = "Key lacks in-game leader permissions"
                    return
                except APIInvalidKey:
                    self.error = "Invalid key. Most likely deleted"
                    return
                except APIError:
                    self.error = "API error"
                    return
                self.ranks = {r["id"]: r["order"] for r in ranks}
                changed = False
                for rank in self.ranks:
                    if rank in self.ranks_to_role_ids:
                        role = self.guild.get_role(self.ranks_to_role_ids[rank])
                        if role:
                            self.roles[rank] = role
                            continue
                    role = await self.create_role(rank=rank)
                    if role:
                        self.roles[rank] = role
                        changed = True
                orphaned = self.ranks_to_role_ids.keys() - self.roles
                for orphan in orphaned:
                    changed = True
                    role = self.guild.get_role(self.ranks_to_role_ids[orphan])
                    await self.safe_role_delete(role)
                self.role_ids_to_ranks = {r.id: k for k, r in self.roles.items()}
                if changed:
                    await self.save(ranks=True)

            else:
                for role_id in self.ranks_to_role_ids.values():
                    role = self.guild.get_role(role_id)
                    await self.safe_role_delete(role)
            if self.last_error and not self.error:
                self.error = None
                await self.save(error=True)

    class SyncTarget:

        @classmethod
        async def create(cls, cog, member, doc=None) -> GuildSync.SyncTarget:
            """`doc` is the member's settings, if already read."""
            self = cls()
            self.member = member
            if doc is None:
                doc = await cog.bot.data.users.get(member.id)
            keys = doc.get("keys", [])
            if not keys:
                key = doc.get("key")
                if key:
                    keys.append(key)
            self.accounts = {key["account_name"] for key in keys}
            self.is_in_any_guild = False
            return self

        async def add_roles(self, roles):
            try:
                coro = self.member.add_roles(*roles, reason="/guildsync")
                await asyncio.wait_for(coro, timeout=5)
            except (asyncio.TimeoutError, discord.Forbidden):
                pass

        async def remove_roles(self, roles):
            try:
                coro = self.member.remove_roles(*roles, reason="/guildsync")
                await asyncio.wait_for(coro, timeout=5)
            except (asyncio.TimeoutError, discord.Forbidden):
                pass

        async def sync_membership(self, sync_guild: GuildSync.SyncGuild):
            lowest_order = float("inf")
            highest_rank = None
            to_add = []
            belongs = False
            current_rank_roles = {}
            current_tag_role = None
            for role in self.member.roles:
                if role.id in sync_guild.role_ids_to_ranks:
                    rank = sync_guild.role_ids_to_ranks[role.id]
                    current_rank_roles[rank] = role
                elif role.id == sync_guild.tag_role_id:
                    current_tag_role = role
            for account in self.accounts:
                if account in sync_guild.members:
                    belongs = True
                    self.is_in_any_guild = True
                    if not sync_guild.ranks_enabled:
                        break
                    if sync_guild.ranks_enabled:
                        rank = sync_guild.members[account]
                        order = sync_guild.ranks.get(rank)
                        if order:
                            if order < lowest_order:
                                lowest_order = order
                                highest_rank = rank
            if sync_guild.ranks_enabled and highest_rank:
                if highest_rank not in current_rank_roles:
                    role = sync_guild.roles.get(highest_rank)
                    if role:
                        if role < self.member.guild.me.top_role:
                            to_add.append(role)
            if sync_guild.tag_enabled and sync_guild.tag_role:
                if not current_tag_role and belongs:
                    to_add.append(sync_guild.tag_role)
            if to_add:
                await self.add_roles(to_add)
            to_remove = []
            for rank in current_rank_roles:
                if rank != highest_rank:
                    to_remove.append(current_rank_roles[rank])
            if not belongs and current_tag_role:
                to_remove.append(current_tag_role)
            if to_remove:
                await self.remove_roles(to_remove)

    async def guildsync_autocomplete(
        self, interaction: discord.Interaction, current: str
    ):

        syncs = await self.db.guildsyncs.find(
            {"guild_id": interaction.guild.id, "name": prepare_search(current)}
        ).to_list(None)
        syncs = [self.SyncGuild(self, doc, interaction.guild) for doc in syncs]
        options = []
        for sync in syncs:
            options.append(Choice(name=sync.guild_name, value=sync.id))
        return options

    @guildsync_group.command(name="diagnose")
    @app_commands.checks.has_permissions(manage_guild=True, manage_roles=True)
    @app_commands.describe(
        sync="The guildsync to debug", user="The user to test the config of"
    )
    @app_commands.autocomplete(sync=guildsync_autocomplete)
    async def guildsync_diagnose(
        self, interaction: discord.Interaction, sync: str, user: discord.User = None
    ):
        """Diagnose common issues with your guildsync configuration."""
        await interaction.response.defer()
        sync = await self.db.guildsyncs.find_one(
            {"guild_id": interaction.guild.id, "gid": sync}
        )
        if not sync:
            return await interaction.followup.send("No valid sync chosen")
        if not interaction.guild.me.guild_permissions.manage_roles:
            return await interaction.followup.send(
                "I don't have the manage roles permission"
            )
        gs = self.SyncGuild(self, sync, interaction.guild)
        key_ok = await self.verify_leader_permissions(gs.key, gs.id)
        if not key_ok:
            return await interaction.followup.send(
                "The added key is no longer valid. "
                "Please change the key using /guildsync edit."
            )
        if not gs.ranks_enabled and not gs.tag_enabled:
            return await interaction.followup.send(
                "Both rank sync and tag role sync are disabled"
            )
        await gs.synchronize_roles()
        if user:
            await gs.fetch_members()
            user_doc = await self.bot.data.users.get(user.id)
            keys = user_doc.get("keys", [])
            if not keys:
                key = user_doc.get("key")
                if key:
                    keys.append(key)
            if not any(key["account_name"] in gs.members for key in keys):
                return await interaction.followup.send(
                    "The provided user " "is not in the guild."
                )
        for rank in gs.roles:
            if gs.roles[rank] > interaction.guild.me.top_role:
                return await interaction.followup.send(
                    f"The synced role {gs.roles[rank]} is higher on the "
                    "hierarchy than my highest role. I am unable to sync it."
                )
        return await interaction.followup.send(
            "Everything seems to be "
            "in order! If you're still having trouble, ask for "
            "help in the support server."
        )

    @guildsync_group.command(name="edit")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        api_key="The API key to use for authorization. Use only if you've "
        "selected the 'Change API key' operation.",
        operation="Select the operation.",
        sync="The guildsync to modify",
    )
    @app_commands.autocomplete(sync=guildsync_autocomplete)
    @app_commands.choices(
        operation=[
            Choice(
                name="Toggle syncing ranks.  If disabled, this will delete "
                "the roles created by the bot.",
                value="ranks",
            ),
            Choice(
                value="guild_role",
                name="Toggle guild role. If disabled, this will delete "
                "the roles created by the bot.",
            ),
            Choice(
                name="Change API key. Make sure to "
                "fill out the api_key optional argument",
                value="change_key",
            ),
            Choice(name="Delete the guildsync", value="delete"),
        ]
    )
    async def guildsync_edit(
        self,
        interaction: discord.Interaction,
        sync: str,
        operation: str,
        api_key: str = None,
    ):
        """Change settings and delete guildsyncs."""

        def bool_to_on(setting):
            if setting:
                return "**ON**"
            return "**OFF**"

        await interaction.response.defer(ephemeral=True)
        if operation == "change_key" and not api_key:
            return await interaction.followup.send(
                "You must fill the API key argument to use this operation.",
                ephemeral=True,
            )
        sync = await self.db.guildsyncs.find_one(
            {"guild_id": interaction.guild.id, "gid": sync}
        )
        if not sync:
            return await interaction.followup.send("No valid sync chosen")
        sync = self.SyncGuild(self, sync, interaction.guild)
        embed = discord.Embed(title="Guildsync", color=self.embed_color)

        if operation == "ranks":
            sync.ranks_enabled = not sync.ranks_enabled
        elif operation == "guild_role":
            sync.tag_enabled = not sync.tag_enabled
        elif operation == "change_key":
            verified = await self.verify_leader_permissions(api_key, sync.id)
            if not verified:
                return await interaction.followup.send(
                    "The API key you provided is invalid.", ephemeral=True
                )
            sync.key = api_key
        elif operation == "delete":
            await sync.delete()
            return await interaction.followup.send(content="Sync successfully deleted")
        await sync.save(edited=True)
        lines = [
            f"Syncing ranks: {bool_to_on(sync.ranks_enabled)}",
            f"Guild role for members: {bool_to_on(sync.tag_enabled)}",
        ]
        description = "\n".join(lines)
        if sync.last_error:
            description += f"\n❗ERROR: {sync.last_error}"
        embed.description = description
        embed = discord.Embed(
            title=f"Post-update {sync.guild_name} settings",
            color=self.embed_color,
            description=description,
        )
        await interaction.followup.send(embed=embed)
        await self.run_guildsyncs(interaction.guild)

    @guildsync_group.command(name="add")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True, manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.choices(
        authentication_method=[
            Choice(
                name="Use your own currently active API key. "
                "You need to be the guild leader",
                value="use_key",
            ),
            Choice(
                name="Have the bot prompt another user for "
                "authorization. If selected, fill out user_to_prompt argument",
                value="prompt_user",
            ),
            Choice(
                name="Enter a key. If selected, fill out the api_key argument",
                value="enter_key",
            ),
        ],
        sync_type=[
            Choice(name="Sync only the in-game ranks", value="ranks"),
            Choice(
                name="Give every member of your guild a "
                "single, guild specific role.",
                value="guild_role",
            ),
            Choice(
                name="Sync both the ranks, and give every "
                "member a guild specific role",
                value="ranks_and_role",
            ),
        ],
    )
    @app_commands.describe(
        guild_name="The guild name of the guild " "you wish to sync with.",
        authentication_method="Select how you want to authenticate "
        "the leadership of the guild",
        sync_type="Select how you want the synced roles to behave.",
        user_to_prompt="The user to prompt for authorization. Use "
        "only if you've selected it as the authentication_method.",
        api_key="The api key to use for authorization. "
        "Use only if you've selected it as the authentication_method.",
    )
    async def guildsync_add(
        self,
        interaction: discord.Interaction,
        guild_name: str,
        sync_type: str,
        authentication_method: str,
        user_to_prompt: discord.User = None,
        api_key: str = None,
    ):
        """Sync your in-game guild ranks with Discord. Add a guild."""
        if authentication_method == "prompt_user" and not user_to_prompt:
            return await interaction.response.send_message(
                "You must specify a user to prompt for authorization", ephemeral=True
            )
        if authentication_method == "enter_key" and not api_key:
            return await interaction.response.send_message(
                "You must specify an API key to use for authorization", ephemeral=True
            )
        endpoint_id = "guild/search?name=" + guild_name.title().replace(" ", "%20")
        await interaction.response.defer(ephemeral=True)
        try:
            guild_ids = await self.call_api(endpoint_id)
            guild_id = guild_ids[0]
            base_ep = f"guild/{guild_id}"
            info = await self.call_api(base_ep)
        except (IndexError, APINotFound):
            return await interaction.followup.send("Invalid guild name")
        if authentication_method == "enter_key":
            if not await self.verify_leader_permissions(api_key, guild_id):
                return await interaction.followup.send(
                    "The provided key is invalid or is missing permissions"
                )
            key = api_key
        if authentication_method == "use_key":
            try:
                await self.call_api(base_ep + "/members", interaction.user, ["guilds"])
                key_doc = await self.fetch_key(interaction.user, ["guilds"])
                key = key_doc["key"]
            except (APIForbidden, APIKeyError):
                return await interaction.followup.send("You are not the guild leader.")
        can_add = await self.can_add_sync(interaction.guild, guild_id)
        if not can_add:
            return await interaction.followup.send(
                "Cannot add this guildsync! You're either syncing with "
                "this guild already, or you've hit the limit of "
                f"{GUILDSYNC_LIMIT} active syncs. "
                f"Check `/guildsync edit`",
                ephemeral=True,
            )
        enabled = {"tag": False, "ranks": False}
        if sync_type == "ranks_and_role":
            enabled["tag"] = True
            enabled["ranks"] = True
        elif sync_type == "ranks":
            enabled["ranks"] = True
        else:
            enabled["tag"] = True
        guild_info = {"enabled": enabled, "name": info["name"], "tag": info["tag"]}
        if authentication_method == "prompt_user":
            try:
                key_doc = await self.fetch_key(user_to_prompt, ["guilds"])
            except APIKeyError:
                return await interaction.followup.send(
                    "The user does not have a valid key"
                )
            key = key_doc["key"]
            try:
                await self.call_api(base_ep + "/members", key=key)
            except APIForbidden:
                return await interaction.followup.send(
                    "The user is missing leader permissions."
                )
            try:
                embed = discord.Embed(title="Guildsync request", color=self.embed_color)
                embed.description = (
                    "User {0.name} (`{0.id}`), an "
                    "Administrator in {0.guild.name} server (`{0.guild.id}`) "
                    "is requesting your authorization in order to enable "
                    "Guildsync for the `{1}` guild, of which you are a leader "
                    "of.\nShould you agree, the bot will use your the API key "
                    "that you currently have active to enable Guildsync. If "
                    "the key is deleted at any point the sync will stop "
                    "working.\n**Your key will never be visible to the "
                    "requesting user or anyone else**".format(
                        interaction.user, info["name"]
                    )
                )
                embed.set_footer(
                    text="Use the buttons below to answer. "
                    "If no response is given within three days this request "
                    "will expire."
                )
                view = GuildSyncPromptUserConfirmView(self)
                msg = await user_to_prompt.send(embed=embed, view=view)
                prompt_doc = {
                    "guildsync_id": guild_id,
                    "guild_id": interaction.guild.id,
                    "requester_id": interaction.user.id,
                    "created_at": datetime.utcnow(),
                    "message_id": msg.id,
                    "options": guild_info,
                }
                await self.db.guildsync_prompts.insert_one(prompt_doc)
                await self.db.guildsync_prompts.create_index(
                    "created_at", expireAfterSeconds=259200
                )
                return await interaction.followup.send(
                    "Message successfully sent. You will be "
                    "notified when the user replies."
                )
            except discord.HTTPException:
                return await interaction.followup.send(
                    "Could not send a message to user - "
                    "they most likely have DMs disabled"
                )
        await self.guildsync_success(
            interaction.guild,
            guild_id,
            destination=interaction.followup,
            key=key,
            options=guild_info,
        )

    async def can_add_sync(self, guild, in_game_guild_id):
        result = await self.db.guildsyncs.find_one(
            {"guild_id": guild.id, "gid": in_game_guild_id}
        )
        if result:
            return False
        count = await self.db.guildsyncs.count_documents({"guild_id": guild.id})
        if count >= GUILDSYNC_LIMIT:
            return False
        return True

    async def guildsync_success(
        self, guild, in_game_guild_id, *, destination, key, options, extra_message=None
    ):
        if extra_message:
            await destination.send(extra_message)
        doc = {
            "guild_id": guild.id,
            "gid": in_game_guild_id,
            "key": key,
            "rank_roles": {},
            "tag_role": None,
        } | options
        can_add = await self.can_add_sync(guild, in_game_guild_id)
        if not can_add:
            return await destination.send(
                "Cannot add guildsync. You've either reached the limit "
                f"of {GUILDSYNC_LIMIT} active syncs, or you're trying to add "
                "one that already exists. See /guildsync edit."
            )
        await self.db.guildsyncs.insert_one(doc)
        guild_doc = await self.bot.data.guilds.get(guild.id)
        sync_doc = guild_doc.get("guildsync", {})
        enabled = sync_doc.get("enabled", None)
        if enabled is None:
            await self.bot.data.guilds.update(guild.id, {"guildsync.enabled": True})
        await destination.send("Guildsync succesfully added!")
        await self.run_guildsyncs(guild)

    @guildsync_group.command(name="toggle")
    @app_commands.guild_only()
    @app_commands.describe(enabled="Enable or disable guildsync for this server")
    @app_commands.checks.has_permissions(manage_guild=True, manage_roles=True)
    async def sync_toggle(self, interaction: discord.Interaction, enabled: bool):
        """Global toggle for guildsync - does not wipe the settings"""
        guild = interaction.guild
        await self.bot.data.guilds.update(guild.id, {"guildsync.enabled": enabled})
        if enabled:
            msg = (
                "Guildsync is now enabled. You may still need to "
                "add guildsyncs using `guildsync add` before it "
                "is functional."
            )
        else:
            msg = (
                "Guildsync is now disabled globally on this server. "
                "Run this command again to enable it."
            )
        await interaction.response.send_message(msg)

    async def guildsync_now(self, ctx):
        """Force a synchronization"""
        await self.run_guildsyncs(ctx.guild)

    @guildsync_group.command(name="purge")
    @app_commands.guild_only()
    @app_commands.describe(
        enabled="Enable or disable purge. You'll be asked to confirm your "
        "selection afterwards."
    )
    @app_commands.checks.has_permissions(
        manage_guild=True, manage_roles=True, kick_members=True
    )
    @app_commands.checks.bot_has_permissions(kick_members=True, manage_roles=True)
    async def sync_purge(self, interaction: discord.Interaction, enabled: bool):
        """Toggle kicking of users that are not in any of the synced guilds."""
        if enabled:
            view = ConfirmPurgeView()
            await interaction.response.send_message(
                "Members without any other role that have been in the "
                "server for longer than 48 hours will be kicked during guild "
                "syncs.",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if view.value is None:
                return await interaction.edit_original_response(
                    content="Timed out.", view=None
                )
            elif view.value:
                await self.bot.data.guilds.update(interaction.guild.id, {"guildsync.purge": enabled})
        else:
            await self.bot.data.guilds.update(interaction.guild.id, {"guildsync.purge": enabled})
            await interaction.response.send_message("Disabled purge.")

    async def verify_leader_permissions(self, key, guild_id):
        try:
            await self.call_api(f"guild/{guild_id}/members", key=key)
            return True
        except APIError:
            return False

    async def run_guildsyncs(self, guild: discord.Guild, *, sync_for=None):
        async with self.sync_locks[guild.id]:
            await self._run_guildsyncs(guild, sync_for=sync_for)

    async def _run_guildsyncs(self, guild, *, sync_for=None):
        guild_doc = await self.bot.data.guilds.get(guild.id)
        guildsync_doc = guild_doc.get("guildsync", {})
        enabled = guildsync_doc.get("enabled", False)
        if not enabled:
            return
        purge = guildsync_doc.get("purge", False)
        cursor = self.db.guildsyncs.find({"guild_id": guild.id})
        targets = []
        if sync_for:
            target = targets.append(await self.SyncTarget.create(self, sync_for))
        else:
            if not guild.chunked:
                await guild.chunk()
            users = await self.users_by_id(member.id for member in guild.members)
            for member in guild.members:
                target = await self.SyncTarget.create(self, member, users.get(member.id, {}))
                if target:
                    targets.append(target)
        # Purging is only safe when every sync read its guild's members:
        # otherwise an API outage or a revoked key looks like everyone left
        synced = 0
        complete = True
        async for doc in cursor:
            try:
                sync = self.SyncGuild(self, doc, guild)
                await sync.synchronize_roles()
                if sync.error:
                    await sync.save(error=True)
                    if sync.ranks_enabled and not sync.roles:
                        complete = False
                        continue
                try:
                    await sync.fetch_members()
                except APIError:
                    sync.error = "Couldn't fetch guild members."
                    await sync.save(error=True)
                    complete = False
                    continue
                for target in targets:
                    await target.sync_membership(sync)
                synced += 1
            except Exception as e:
                complete = False
                self.log.exception("Exception in guildsync", exc_info=e)
        if purge and not complete:
            self.log.warning(
                "Guildsync: skipping purge in %s, not every guild's members could be read", guild.id)
        elif purge and synced:
            for target in targets:
                member = target.member
                membership_duration = (
                    discord.utils.utcnow() - member.joined_at
                ).total_seconds()
                if not target.is_in_any_guild:
                    if len(member.roles) == 1 and membership_duration > 172800:
                        try:
                            await member.guild.kick(
                                user=member, reason="/guildsync purge"
                            )
                        except discord.Forbidden:
                            pass

    async def inspect_server(self, guild_id):
        """What guild sync sees in a server, for debugging: each sync's
        saved roles, whether the bot's cache and Discord have them, the
        in-game ranks, and every role named like a rank. Never the key."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return f"Not in server {guild_id}"
        me = guild.me
        try:
            fetched = {role.id: role for role in await guild.fetch_roles()}
        except discord.HTTPException as e:
            fetched = {}
            lines = [f"Couldn't fetch roles from Discord: {e}"]
        else:
            lines = []

        def describe(role):
            members = f", {len(role.members)} members" if guild.chunked else ""
            return f"{role.name!r} at {role.position}{members}"

        def lookup(role_id):
            cached, live = guild.get_role(role_id), fetched.get(role_id)
            return (f"cache: {describe(cached) if cached else 'MISSING'} | "
                    f"Discord: {describe(live) if live else 'MISSING'}")

        lines[:0] = [
            f"Server {guild.name!r} ({guild.id}), chunked: {guild.chunked}",
            f"Bot's top role: {me.top_role.name!r} at {me.top_role.position}, "
            f"manage roles: {me.guild_permissions.manage_roles}",
            f"Roles cached: {len(guild.roles)}, on Discord: {len(fetched)}",
        ]
        settings = (await self.bot.data.guilds.get(guild.id)).get("guildsync", {})
        lines.append(f"Guild sync enabled: {settings.get('enabled')}, purge: {settings.get('purge')}")
        async for doc in self.db.guildsyncs.find({"guild_id": guild.id}):
            lines += ["", f"Sync {doc['_id']}: {doc.get('name')!r} [{doc.get('tag')}] {doc.get('gid')}",
                      f"  enabled: {doc.get('enabled')}, error: {doc.get('error')!r}"]
            tag_role = doc.get("tag_role")
            if tag_role:
                lines.append(f"  tag role {tag_role} ({type(tag_role).__name__}): {lookup(tag_role)}")
            lines.append("  rank roles saved:")
            for rank, role_id in doc.get("rank_roles", {}).items():
                lines.append(f"    {rank!r} -> {role_id} ({type(role_id).__name__}): {lookup(role_id)}")
            try:
                ranks = await self.call_api(f"guild/{doc['gid']}/ranks", key=doc["key"])
            except APIError as e:
                lines.append(f"  in-game ranks: couldn't read ({type(e).__name__}: {e})")
                continue
            lines.append(f"  in-game ranks: {[rank['id'] for rank in ranks]!r}")
            names = {rank["id"].strip().lower() for rank in ranks}
            names |= {rank.strip().lower() for rank in doc.get("rank_roles", {})}
            alike = [role for role in fetched.values() if role.name.strip().lower() in names]
            lines.append("  roles on Discord named like a rank:")
            for role in sorted(alike, key=lambda r: (r.name.lower(), r.id)):
                lines.append(f"    {role.id}: {describe(role)}, cached: {guild.get_role(role.id) is not None}")
        return "\n".join(lines)

    async def repair_replaced_roles(self, entries, *, apply=False):
        """Link synced ranks back to the roles they had before guild sync
        replaced them with new ones, and delete the replacements.

        `entries` are {"sync": sync id, "guild_id": server id,
        "roles": {rank: [old role id, replacement role id]}}. A rank is
        only relinked if it still points at the replacement and the old
        role still exists, below the bot's top role. Nothing changes
        unless `apply`. Returns (counts of each outcome, a line per sync).
        """
        counts = collections.Counter()
        lines = []
        for entry in entries:
            guild_id = int(entry["guild_id"])
            guild = self.bot.get_guild(guild_id)
            if not guild:
                outcome, details = "bot not in server", ""
            else:
                async with self.sync_locks[guild_id]:
                    outcome, details = await self._repair_sync(guild, entry, apply, counts)
            counts[f"sync {outcome}"] += 1
            lines.append(f"{guild_id} {entry['sync']}: {outcome}" + (f" - {details}" if details else ""))
        return counts, lines

    async def _repair_sync(self, guild, entry, apply, counts):
        """Repair one sync (see repair_replaced_roles). Returns its outcome
        and what happened to each rank."""
        try:
            sync_id = ObjectId(entry["sync"])
        except InvalidId:
            sync_id = entry["sync"]
        doc = await self.db.guildsyncs.find_one({"_id": sync_id, "guild_id": guild.id})
        if not doc:
            return "sync removed", ""
        if not guild.me.guild_permissions.manage_roles:
            return "can't manage roles", ""
        # From Discord rather than the cache, to be sure a role is gone
        try:
            roles = {role.id: role for role in await guild.fetch_roles()}
        except discord.HTTPException:
            return "couldn't fetch roles", ""
        rank_roles = dict(doc["rank_roles"])
        relinked, replacements, skipped = [], [], []
        for rank, (old_id, new_id) in entry["roles"].items():
            old_id, new_id = int(old_id), int(new_id)
            old = roles.get(old_id)
            if rank_roles.get(rank) != new_id:
                reason = "changed since"
            elif not old:
                reason = "old role deleted"
            elif not old < guild.me.top_role:
                reason = "old role above the bot's"
            else:
                rank_roles[rank] = old_id
                relinked.append(rank)
                if new_id in roles:
                    replacements.append(roles[new_id])
                continue
            skipped.append(f"{rank} ({reason})")
            counts[f"rank kept: {reason}"] += 1
        counts["rank relinked"] += len(relinked)
        if apply and relinked:
            await self.db.guildsyncs.update_one({"_id": doc["_id"]}, {"$set": {"rank_roles": rank_roles}})
            for role in replacements:
                try:
                    await role.delete(reason="Guild sync repair: the rank uses its old role again")
                    counts["replacement deleted"] += 1
                except discord.HTTPException:
                    skipped.append(f"couldn't delete {role.name} ({role.id})")
                    counts["replacement not deleted"] += 1
        details = [f"relinked {', '.join(relinked)}"] if relinked else []
        if skipped:
            details.append(f"kept {', '.join(skipped)}")
        return "repaired" if relinked else "nothing to relink", "; ".join(details)

    @tasks.loop(seconds=60)
    async def guild_synchronizer(self):
        cursor = self.bot.data.guilds.find({"guildsync.enabled": True}, batch_size=10)
        async for doc in cursor:
            try:
                guild = self.bot.get_guild(doc["_id"])
                if guild:
                    coro = self.run_guildsyncs(guild)
                    await asyncio.wait_for(coro, timeout=200)
            except asyncio.CancelledError:
                return
            except Exception:
                self.log.exception("Couldn't run guild sync in server %s", doc["_id"])

    @guild_synchronizer.before_loop
    async def before_guild_synchronizer(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener("on_member_join")
    async def guildsync_on_member_join(self, member):
        if member.bot:
            return
        guild = member.guild
        doc = await self.bot.data.guilds.get(guild.id)
        sync = doc.get("guildsync", {})
        enabled = sync.get("enabled", False)
        if enabled:
            await self.run_guildsyncs(guild, sync_for=member)


async def setup(bot):
    await bot.add_cog(GuildSync(bot))
