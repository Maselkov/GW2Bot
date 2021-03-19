from __future__ import annotations

import asyncio
from datetime import datetime

import discord
from discord.enums import Enum
from discord.errors import HTTPException
from discord.ext import commands, tasks
from discord.ext.commands.cooldowns import BucketType

from ..exceptions import (APIError, APIForbidden, APIInvalidKey, APIKeyError,
                          APINotFound)

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


class GuildSync:
    # The good ol switcheroo
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

        async def fetch_members(self):
            ep = self.base_ep + "members"
            results = await self.cog.call_api(endpoint=ep, key=self.key)
            self.members = {r["name"]: r["rank"] for r in results}

        async def create_role(self, rank=None):
            if rank:
                name = rank
            else:
                name = self.guild_name
            return await self.guild.create_role(name=name,
                                                reason="$guildsync",
                                                color=discord.Color(
                                                    self.cog.embed_color))

        async def save(self,
                       *,
                       ranks=False,
                       tag_role=False,
                       edited=False,
                       error=False):
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
            await self.cog.db.guildsyncs.update_one({"_id": self.doc_id},
                                                    {"$set": update})

        async def delete(self):
            await self.cog.db.guildsyncs.delete_one({"_id": self.doc_id})
            for role_id in self.ranks_to_role_ids.values():
                await self.safe_role_delete(self.guild.get_role(role_id))
            await self.safe_role_delete(self.guild.get_role(self.tag_role_id))

        async def safe_role_delete(self, role):
            if role:
                try:
                    await role.delete(reason="$guildsync - role removed "
                                      "or renamed in-game")
                except HTTPException:
                    pass

        async def synchronize_roles(self):
            if self.tag_enabled:
                self.tag_role = self.guild.get_role(self.tag_role_id)
                if not self.tag_role:
                    try:
                        role = await self.create_role()
                        self.tag_role = role
                        self.tag_role_id = role.id
                        await self.save(tag_role=True)
                    except discord.Forbidden:
                        self.error = "Bot lacks permission to create roles."
            else:
                if self.tag_role_id:
                    role = self.guild.get_role(self.tag_role_id)
                    await self.safe_role_delete(role)
                    self.tag_role = None
                    self.tag_role_id = None
                    await self.save(tag_role=True)
            if self.ranks_enabled:
                ep = f"guild/{self.id}/ranks"
                try:
                    ranks = await self.cog.call_api(ep, key=self.key)
                except APIForbidden:
                    self.error = "Key has in-game leader permissions"
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
                        role = self.guild.get_role(
                            self.ranks_to_role_ids[rank])
                        if role:
                            self.roles[rank] = role
                            continue
                    try:
                        self.roles[rank] = await self.create_role(rank=rank)
                    except discord.Forbidden:
                        self.error = "Bot lacks permission to create roles."
                    changed = True
                orphaned = self.role_ids_to_ranks.keys() - self.roles
                for orphan in orphaned:
                    changed = True
                    role = self.guild.get_role(self.ranks_to_role_ids[orphan])
                    await self.safe_role_delete(role)
                self.role_ids_to_ranks = {
                    r.id: k
                    for k, r in self.roles.items()
                }
                if changed:
                    await self.save(ranks=True)
                if self.last_error:
                    self.error = None
                    await self.save(error=True)
            else:
                for role_id in self.ranks_to_role_ids.values():
                    role = self.guild.get_role(role_id)
                    await self.safe_role_delete(role)

    class SyncTarget:
        @classmethod
        async def create(cls, cog, member) -> GuildSync.SyncTarget:
            self = cls()
            self.member = member
            doc = await cog.bot.database.get(member, cog)
            keys = doc.get("keys", [])
            if not keys:
                key = doc.get("key")
                if key:
                    keys.append(key)
            self.accounts = {key["account_name"] for key in keys}
            self.is_in_any_guild = False
            return self

        async def add_roles(self, roles):
            await self.member.add_roles(*roles, reason="$guildsync")

        async def remove_roles(self, roles):
            await self.member.remove_roles(*roles, reason="$guildsync")

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
                        order = sync_guild.ranks[rank]
                        if order < lowest_order:
                            lowest_order = order
                            highest_rank = rank
            if sync_guild.ranks_enabled and highest_rank:
                if highest_rank not in current_rank_roles:
                    to_add.append(sync_guild.roles[highest_rank])
            if sync_guild.tag_enabled and sync_guild.tag_role:
                if not current_tag_role and belongs:
                    to_add.append(sync_guild.tag_role)
            if to_add:
                try:
                    await self.add_roles(to_add)
                except discord.Forbidden:
                    pass
                    # Notify code here
            to_remove = []
            for rank in current_rank_roles:
                if rank != highest_rank:
                    to_remove.append(current_rank_roles[rank])
            if not belongs and current_tag_role:
                to_remove.append(current_tag_role)
            if to_remove:
                try:
                    await self.remove_roles(to_remove)
                except discord.Forbidden:
                    pass
                    # Notify code here

    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.group(name="guildsync", case_insensitive=True)
    async def guildsync(self, ctx):
        """In game guild rank to discord roles synchronization commands
        This group allows you to set up a link between your roster and Discord.
        When enabled, new roles will be created for each of your ingame ranks,
        and ingame members are periodically synced to have the
        correct role in discord."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @guildsync.command(name="setup", hidden=True)
    async def legacy_guildsync_setup(self, ctx):
        return await ctx.send(
            "*Guildsync now supports multiple guilds. "
            f"This command has been deprecated\n\nUse **{ctx.prefix}guildsync "
            "add** instead for setup")

    @commands.bot_has_permissions(add_reactions=True, embed_links=True)
    @commands.has_permissions(administrator=True)
    @guildsync.command(name="edit", aliases=["clear"])
    async def guildsync_edit(self, ctx):
        """Change settings and delete guildsyncs."""
        def bool_to_on(setting):
            if setting:
                return "**ON**"
            return "**OFF**"

        can_edit = ctx.channel.permissions_for(ctx.me).manage_messages
        syncs = await self.db.guildsyncs.find({
            "guild_id": ctx.guild.id
        }).to_list(None)
        if not syncs:
            return await ctx.send(
                "This server currently has no active guildsyncs.")
        embed = discord.Embed(title="Currently synced guilds",
                              color=self.embed_color)
        syncs = [self.SyncGuild(self, doc, ctx.guild) for doc in syncs]
        if len(syncs) != 1:
            for i, sync in enumerate(syncs, start=1):
                ranks = bool_to_on(sync.ranks_enabled)
                tag = bool_to_on(sync.tag_enabled)
                settings = (f"Syncing guild ranks: {ranks}\nGuild role for "
                            f"members: {tag}")
                if sync.last_error:
                    settings += f"\n❗ERROR: {sync.last_error}"
                embed.add_field(name=f"**{i}.** {sync.guild_name}",
                                value=settings)
            numbers = []
            for i in range(1, i + 1):
                emoji = f"{i}\N{combining enclosing keycap}"
                numbers.append(emoji)

            message = await ctx.send(embed=embed)
            for number in numbers:
                await message.add_reaction(number)
            reaction = await ctx.get_reaction(message, numbers)
            if not reaction:
                return await message.edit(suppress=True)
            option = numbers.index(reaction.emoji)
            if can_edit:
                await message.clear_reactions()
        else:
            option = 0
            message = None
        sync = syncs[option]

        initial = True

        class Option(Enum):
            TOGGLE_RANKS = "📃"
            TOGGLE_TAG = "📛"
            CHANGE_KEY = "🔑"
            DELETE = "❌"
            SAVE = "✅"

        emojis = [e.value for e in Option]
        initial_ranks = sync.ranks_enabled
        initial_tag = sync.tag_enabled
        ranks_were_disabled = False
        tag_was_disabled = False

        while True:
            role_warning = ranks_were_disabled or tag_was_disabled
            embed = discord.Embed(title=f"Editing {sync.guild_name} sync",
                                  color=self.embed_color)
            description = (
                f"Syncing ranks: {bool_to_on(sync.ranks_enabled)}\n"
                f"Guild role for members: {bool_to_on(sync.tag_enabled)}")
            if role_warning:
                description += (
                    "\n❗Toggling a setting off will delete existing roles "
                    "that fall under that setting. They will be recreated if "
                    "the setting is turned back on.")
            if sync.last_error:
                description += f"\n❗ERROR: {sync.last_error}"
            embed.description = description
            embed.add_field(name="Options",
                            value="📃 - Toggle syncing ranks"
                            "\n📛 - Toggle guild role"
                            "\n🔑 - Change API key"
                            "\n❌ - Delete this guildsync"
                            "\n✅ - Close menu and save changes")
            if can_edit and message:
                asyncio.create_task(message.edit(embed=embed))
            else:
                if message:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass
                message = await ctx.send(embed=embed)
            if not can_edit or initial:

                async def add_emojis():
                    for emoji in emojis:
                        await message.add_reaction(emoji)

                asyncio.create_task(add_emojis())
            initial = False
            reaction = await ctx.get_reaction(message, emojis)
            if not reaction:
                try:
                    return await message.delete()
                except discord.HTTPException:
                    try:
                        return await message.edit(suppress=True)
                    except discord.HTTPException:
                        pass
            option = Option(reaction.emoji)
            if can_edit:
                try:
                    asyncio.create_task(reaction.remove(ctx.author))
                except discord.HTTPException:
                    pass
            if option == Option.TOGGLE_RANKS:
                sync.ranks_enabled = not sync.ranks_enabled
                if not sync.ranks_enabled and initial_ranks:
                    ranks_were_disabled = True
            elif option == Option.TOGGLE_TAG:
                sync.tag_enabled = not sync.tag_enabled
                if not sync.tag_enabled and initial_tag:
                    tag_was_disabled = True
            elif option == Option.CHANGE_KEY:
                key = await self.prompt_for_leader_key(ctx, sync.id)
                if key:
                    sync.key = key
            elif option == Option.DELETE:
                response = await ctx.get_answer("Are you sure you want to"
                                                "delete this sync? To "
                                                "confirm, type `yes` in chat.")
                if not response:
                    return
                if response.lower().startswith("y"):
                    await sync.delete()
                    await ctx.send("Sync successfully deleted")
                    if can_edit:
                        try:
                            await message.clear_reactions()
                        except discord.HTTPException:
                            pass
                    return
                await ctx.send("Unrecognized answer")
            elif option == Option.SAVE:
                await sync.save(edited=True)
                await ctx.send("Successfully saved!")
                if can_edit:
                    await message.clear_reactions()
                self.schedule_guildsync(ctx.guild, 1)
                return

    async def prompt_for_leader_key(self, ctx, guild_id):
        response = await ctx.get_answer(
            "Copy paste the API key you wish to use into the chat now. "
            "The bot will delete your message (provided that enough "
            "permissions have been given)",
            return_full=True)
        if not response:
            return
        try:
            await response.delete()
        except discord.HTTPException:
            pass
        if not response:
            return None
        verified = await self.verify_leader_permissions(
            response.content, guild_id)
        if not verified:
            await ctx.send("This key is invalid or is missing permissions")
            return None
        if verified:
            return response.content
        return None

    @commands.bot_has_permissions(manage_roles=True,
                                  add_reactions=True,
                                  embed_links=True)
    @commands.has_permissions(administrator=True)
    @guildsync.command(name="add")
    async def guildsync_add(self, ctx):
        """Add a new guildsync. This is the setup command."""
        def msg_check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        prompt = ("Please type the name of the in-game guild you wish to sync "
                  "with. Ensure you respond exactly as it is written in-game.")
        guild_name = await ctx.get_answer(prompt, timeout=260, check=msg_check)
        if not guild_name:
            return
        endpoint_id = "guild/search?name=" + guild_name.title().replace(
            ' ', '%20')
        can_edit = ctx.channel.permissions_for(ctx.me).manage_messages
        try:
            guild_ids = await self.call_api(endpoint_id)
            guild_id = guild_ids[0]
            base_ep = f"guild/{guild_id}"
            info = await self.call_api(base_ep)
        except (IndexError, APINotFound):
            return await ctx.send("Invalid guild name")
        except APIError as e:
            return await self.error_handler(ctx, e)
        can_add = await self.can_add_sync(ctx.guild, guild_id)
        if not can_add:
            return await ctx.send(
                "Cannot add this guildsync! You're either syncing with "
                "this guild already, or you've hit the limit of "
                f"{GUILDSYNC_LIMIT} active syncs. "
                f"Check `{ctx.prefix}guildsync edit`")
        embed = discord.Embed(title="Sync Type", color=self.embed_color)
        embed.description = ("Select a sync type. You can always change this "
                             "later using **$guildsync edit**")
        fields = [
            [
                "**1.** Ranks and Guild Role",
                "This option will sync in-game ranks Discord roles, as "
                "well as give every member a guild-specific role for easy "
                "permission management. The bot will create roles as needed."
                "\n**Recommended if you are unsure**"
            ],
            [
                "**2.** Ranks Only",
                "The same as above, but without the Guild Role for all"
                " members."
            ],
            [
                "**3.** Guild Role Only",
                "This option will not sync in-game ranks - it will only "
                "grant all members the same, guild specific role\nRecommended "
                "for large alliance servers spanning multiple guilds."
            ]
        ]
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
        numbers = []
        for i in range(1, 4):
            emoji = f"{i}\N{combining enclosing keycap}"
            numbers.append(emoji)
        message = await ctx.send(embed=embed)

        for number in numbers:
            await message.add_reaction(number)
        enabled = {"tag": False, "ranks": False}
        reaction = await ctx.get_reaction(message, numbers, timeout=300)
        if not reaction:
            try:
                await ctx.send("No reaction in time")
                return await message.delete()
            except discord.HTTPException:
                return
        option = numbers.index(reaction.emoji)
        if option == 0:
            enabled["tag"] = True
            enabled["ranks"] = True
        elif option == 1:
            enabled["ranks"] = True
        else:
            enabled["tag"] = True
        try:
            await message.clear_reactions()
        except discord.HTTPException:
            pass
        embed = discord.Embed(title=info["name"], color=self.embed_color)
        is_leader = True
        try:
            await self.call_api(base_ep + "/members", ctx.author, ["guilds"])
        except (APIForbidden, APIKeyError):
            is_leader = False
        embed.description = (
            "For the next step you will need to select how you wish to handle "
            "the authentication, as checking the guild ranks requires an API "
            "key with Guild Leader permissions.")
        fields = [
            [
                "**1.** Use your own currently active API key",
                "The bot will use your current API key to handle "
                "authentication. You need to be an in-game leader and the "
                "sync will stop working should the key be deleted. It is "
                "therefore recommended that you make a separate API key "
                "for Guildsync, but it is not requried.\n**This option is "
                "most likely what you want if you don't know what to select.**"
            ],
            [
                "**2.** Have the bot prompt another user for authorization",
                "The bot will DM a server member that you point to and ask "
                "them to allow Guildsync to access their currently active API "
                "key. They need to have in-game Leader permissions and it is "
                "recommended that they make a separate API key for Guildsync."
                "\n**This option is most useful in case of alliance servers "
                "that span multiple, separate guilds.**"
            ],
            [
                "**3.** Enter a key",
                "The bot will prompt you for an API key that will be used "
                "for authorization."
            ]
        ]
        if not is_leader:
            fields[0][0] = f"~~{fields[0][0]}~~"
            fields[0][1] = (
                f"~~{fields[0][1]}~~\n\n**This option is unavailable since "
                "you do not have enough in-game permissions.**")
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
        if can_edit:
            await message.edit(embed=embed)
        else:
            message = await ctx.send(embed=embed)
        if not is_leader:
            numbers.pop(0)
        for number in numbers:
            await message.add_reaction(number)
        reaction = await ctx.get_reaction(message, numbers, timeout=300)
        if not reaction:
            try:
                await ctx.send("No reaction in time")
                return await message.delete()
            except discord.HTTPException:
                return
        option = numbers.index(reaction.emoji)
        if not is_leader:
            option += 1
        guild_info = {
            "enabled": enabled,
            "name": info["name"],
            "tag": info["tag"]
        }
        try:
            await message.clear_reactions()
        except discord.HTTPException:
            pass
        if option == 0:
            if not is_leader:
                return await ctx.send(
                    "You need to be a leader to select this option")
            key_doc = await self.fetch_key(ctx.author)
            key = key_doc["key"]
        elif option == 2:
            key = await self.prompt_for_leader_key(ctx, guild_id)
            if not key:
                return
        elif option == 1:
            prompt = (
                "Please @mention the user that you wish the bot to prompt.")
            answer = await ctx.get_answer(prompt,
                                          timeout=260,
                                          check=msg_check,
                                          return_full=True)
            if not answer:
                return
            if len(answer.mentions) != 1:
                return await ctx.send("Invalid answer. Aborting.")
            user = answer.mentions[0]
            if user not in ctx.guild.members:
                return await ctx.send("This user is not in this server")
            try:
                key_doc = await self.fetch_key(user, ["guilds"])
            except APIKeyError:
                return await ctx.send("The user does not have a valid key")
            key = key_doc["key"]
            try:
                await self.call_api(base_ep + "/members", key=key)
            except APIForbidden:
                return await ctx.send("The user is missing leader permissions."
                                      )

            try:
                embed = discord.Embed(title="Guildsync request",
                                      embed=self.embed_color)
                embed.description = (
                    "User {0.name}#{0.discriminator} (`{0.id}`), an "
                    "Administrator in {0.guild.name} server (`{0.guild.id}`) "
                    "is requesting your authorization in order to enable "
                    "Guildsync for the `{1}` guild, of which you are a leader "
                    "of.\nShould you agree, the bot will use your the API key "
                    "that you currently have active to enable Guildsync. If "
                    "the key is deleted at any point the sync will stop "
                    "working.\n**Your key will never be visible to the "
                    "requesting user or anyone else**".format(
                        ctx.author, info["name"]))
                embed.set_footer(
                    text="Use the reactions below to answer. "
                    "If no response is given within three days this request "
                    "will expire.")
                msg = await user.send(embed=embed)
                for emoji in PROMPT_EMOJIS:
                    await msg.add_reaction(emoji)
                prompt_doc = {
                    "guildsync_id": guild_id,
                    "guild_id": ctx.guild.id,
                    "requester_id": ctx.author.id,
                    "created_at": datetime.utcnow(),
                    "message_id": msg.id,
                    "options": guild_info
                }
                await self.db.guildsync_prompts.insert_one(prompt_doc)
                await self.db.guildsync_prompts.create_index(
                    "created_at", expireAfterSeconds=259200)
                return await ctx.send("Message successfully sent. You will be "
                                      "notified when the user replies.")
            except discord.HTTPException:
                return await ctx.send("Could not send a message to user - "
                                      "they most likely have DMs disabled")
        await self.guildsync_success(ctx.guild,
                                     guild_id,
                                     destination=ctx,
                                     key=key,
                                     options=guild_info)

    async def can_add_sync(self, guild, in_game_guild_id):
        result = await self.db.guildsyncs.find_one({
            "guild_id": guild.id,
            "gid": in_game_guild_id
        })
        if result:
            return False
        count = await self.db.guildsyncs.count_documents(
            {"guild_id": guild.id})
        if count > GUILDSYNC_LIMIT:
            return False
        return True

    async def guildsync_success(self,
                                guild,
                                in_game_guild_id,
                                *,
                                destination,
                                key,
                                options,
                                extra_message=None):
        if extra_message:
            await destination.send(extra_message)
        doc = {
            "guild_id": guild.id,
            "gid": in_game_guild_id,
            "key": key,
            "rank_roles": {},
            "tag_role": None
        } | options
        can_add = await self.can_add_sync(guild, in_game_guild_id)
        if not can_add:
            return await destination.send(
                "Cannot add guildsync. You've either reached the limit "
                f"of {GUILDSYNC_LIMIT} active syncs, or you're trying to add "
                "one that already exists. See $guildsync edit.")
        await self.db.guildsyncs.insert_one(doc)
        guild_doc = await self.bot.database.get(guild, self)
        sync_doc = guild_doc.get("guildsync", {})
        enabled = sync_doc.get("enabled", None)
        if enabled is None:
            await self.bot.database.set(guild, {"guildsync.enabled": True},
                                        self)
        await destination.send("Guildsync succesfully added!")
        self.schedule_guildsync(guild, 0)

    @commands.has_permissions(administrator=True)
    @guildsync.command(name="toggle")
    async def sync_toggle(self, ctx, on_off: bool):
        """Global toggle for synchronization - does not wipe the settings"""
        guild = ctx.guild
        await self.bot.database.set_guild(guild, {"guildsync.enabled": on_off},
                                          self)
        if on_off:
            msg = ("Guildsync is now enabled. You may still need to "
                   "add guildsyncs using `guildsync add` before it "
                   "is functional.")
        else:
            msg = ("Guildsync is now disabled globally on this server. "
                   "Run this command again to enable it.")
        await ctx.send(msg)

    @guildsync.command(name="now")
    @commands.cooldown(1, 60, BucketType.user)
    async def sync_now(self, ctx):
        """Force a synchronization"""
        await ctx.send("Ran guildsync.")
        self.schedule_guildsync(ctx.guild, 0)

    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(add_reactions=True)
    @guildsync.command(name="purge")
    async def sync_purge(self, ctx, on_off: bool):
        """Toggles kicking of users that are not in any of the linked guilds.
        Discord users not in the  are kicked if this is enabled unless they
        have any other non-guildsync role or have been in the server for
        less than 48 hours."""
        if on_off:
            await ctx.send(
                "Members without any other role that have been in the "
                "server for longer than 48 hourswill be kicked during guild "
                "syncs.")
            message = await ctx.send(
                "Are you sure you want to enable this? React ✔ to confirm.")
            await message.add_reaction("✔")
            reaction = await ctx.get_reaction(message, ["✔"])
            if not reaction:
                await ctx.send("No response in time.")
                return
            await ctx.send("Enabled.")
            await self.bot.database.set(ctx.guild, {"guildsync.purge": on_off},
                                        self)
            try:
                await message.clear_reactions()
            except discord.HTTPException:
                pass
        else:
            await self.bot.database.set(ctx.guild, {"guildsync.purge": on_off},
                                        self)
            await ctx.send("Disabled automatic purging.")

    async def verify_leader_permissions(self, key, guild_id):
        try:
            await self.call_api(f"guild/{guild_id}/members", key=key)
            return True
        except APIError:
            return False

    async def run_guildsyncs(self, guild, *, sync_for=None):
        guild_doc = await self.bot.database.get(guild, self)
        guildsync_doc = guild_doc.get("guildsync", {})
        enabled = guildsync_doc.get("enabled", False)
        if not enabled:
            return
        purge = guildsync_doc.get("purge", False)
        cursor = self.db.guildsyncs.find({"guild_id": guild.id})
        targets = []
        if sync_for:
            target = targets.append(await
                                    self.SyncTarget.create(self, sync_for))
        else:
            for member in guild.members:
                target = await self.SyncTarget.create(self, member)
                if target:
                    targets.append(target)
        async for doc in cursor:
            try:
                sync = self.SyncGuild(self, doc, guild)
                await sync.synchronize_roles()
                if sync.error:
                    await sync.save(error=True)
                    if sync.ranks_enabled and not sync.roles:
                        continue
                try:
                    await sync.fetch_members()
                except APIError:
                    sync.error = "Couldn't fetch guild members."
                    await sync.save(error=True)
                    continue
                for target in targets:
                    await target.sync_membership(sync)

            except Exception as e:
                self.log.exception("Exception in guildsync", exc_info=e)
        if purge:
            for target in targets:
                member = target.member
                membership_duration = (datetime.datetime.utcnow() -
                                       member.joined_at).total_seconds()
                if not target.is_in_any_guild:
                    if len(member.roles) == 1 and membership_duration > 172800:
                        await member.guild.kick(user=member,
                                                reason="$guildsync purge")

    async def guildsync_consumer(self):
        while True:
            try:
                _, coro = await self.guildsync_queue.get()
                await coro
            except Exception as e:
                self.log.exception("Exception in guildsync consumer",
                                   exc_info=e)
            finally:
                try:
                    self.guildsync_queue.task_done()
                except ValueError as e:
                    self.log.exception("Error in guildsync consumer",
                                       exc_info=e)
            await asyncio.sleep(0.5)

    @tasks.loop(seconds=60)
    async def guild_synchronizer(self):
        cursor = self.bot.database.iter("guilds", {"guildsync.enabled": True},
                                        self,
                                        batch_size=20,
                                        subdocs=["sync"])
        async for doc in cursor:
            try:
                if doc["_obj"]:
                    self.schedule_guildsync(doc["_obj"], 2)
            except asyncio.CancelledError:
                return
            except Exception:
                pass
        await self.guildsync_queue.join()

    def schedule_guildsync(self, guild, priority, *, member=None):
        coro = self.run_guildsyncs(guild, sync_for=member)
        self.guildsync_entry_number += 1
        self.guildsync_queue.put_nowait(
            ((priority, self.guildsync_entry_number), coro))

    @commands.Cog.listener("on_member_join")
    async def guildsync_on_member_join(self, member):
        if member.bot:
            return
        guild = member.guild
        doc = await self.bot.database.get(guild, self)
        sync = doc.get("guildsync", {})
        enabled = sync.get("enabled", False)
        if enabled:
            self.schedule_guildsync(guild, 1, member=member)

    @commands.Cog.listener("on_raw_reaction_add")
    async def handle_guildsync_prompt_answers(
            self, payload: discord.RawReactionActionEvent):
        if payload.guild_id:
            return
        if payload.user_id == self.bot.user.id:
            return
        emoji = payload.emoji
        if not emoji.is_unicode_emoji():
            return
        if str(emoji) not in PROMPT_EMOJIS:
            return
        emoji = str(emoji)
        answer = not PROMPT_EMOJIS.index(emoji)
        query = {"message_id": payload.message_id}
        doc = await self.db.guildsync_prompts.find_one(query)
        if not doc:
            return
        user = self.bot.get_user(payload.user_id)
        if not answer:
            await self.db.guildsync_prompts.delete_one(query)
            return await user.send(
                "Noted, request rejected.\nNote that only "
                "admins can send guildsync requests - if you're being "
                "harassed then it is recommended to report them or to leave "
                "the server.")
        try:
            key = await self.fetch_key(user, scopes=["guilds"])
            key = key["key"]
        except APIKeyError:
            return await user.send(
                "It seems like your key is invalid. Try switching your key "
                "and then try again by removing your reaction and adding "
                "it back.")
        in_game_guild_id = doc["guildsync_id"]
        is_leader = await self.verify_leader_permissions(key, in_game_guild_id)
        if not is_leader:
            return await user.send(
                "It seems like your key does not have the necessary in-game "
                "permissions. Try switching your key, then try again by "
                "removing and adding the reaction")
        guild = self.bot.get_guild(doc["guild_id"])
        if not guild:
            return await user.send("It seems like the server no longer exists")
        requesting_user = self.bot.get_user(doc["requester_id"])
        if not requesting_user:
            return await user.send("It seems like the requesting user no "
                                   "longer exists")
        await self.guildsync_success(
            guild,
            in_game_guild_id,
            key=key,
            destination=requesting_user,
            options=doc["options"],
            extra_message="User {0.name}#{0.discriminator} has accepted your "
            "request for Guildsync authorization in {1.name}. "
            "Guild: {2}".format(user, guild, doc["options"]["name"]))
        await user.send("Guildsync successfully enabled! Thank you.")
        await self.db.guildsync_prompts.delete_one(query)
