"""Discord: servers, roles, members, channels and attachments."""
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

UTC = datetime.timezone.utc


def _forbidden():
    import discord

    return discord.Forbidden(MagicMock(status=403), "Missing Permissions")


def _not_found():
    import discord

    return discord.NotFound(MagicMock(status=404), "Unknown Message")


class FakeRole:
    """A role; compared by position like discord.Role."""

    def __init__(self, server, role_id, name, position):
        self.server, self.id, self.name, self.position = server, role_id, name, position

    def __lt__(self, other):
        return self.position < other.position

    def __gt__(self, other):
        return self.position > other.position

    def __le__(self, other):
        return self.position <= other.position

    def __ge__(self, other):
        return self.position >= other.position

    def __repr__(self):
        return f"<role {self.name}>"

    async def delete(self, reason=None):
        self.server.deleted.append(self.name)
        self.server.roles.pop(self.id, None)
        for member in self.server.members:
            if self in member.roles:
                member.roles.remove(self)


class FakeMember:
    """A member; role changes apply to `roles` and are recorded in
    `changes` as ("add" / "remove", [role ids])."""

    def __init__(self, server, member_id, roles=(), days_on_server=3):
        self.id, self.guild, self.bot = member_id, server, False
        self.display_name = self.name = f"Member {member_id}"
        self.roles = ([server.everyone] if server else []) + list(roles)
        self.joined_at = datetime.datetime.now(UTC) - datetime.timedelta(days=days_on_server)
        self.changes = []

    @property
    def mention(self):
        return f"<@{self.id}>"

    def role_names(self):
        return sorted(r.name for r in self.roles if r is not self.guild.everyone)

    async def add_roles(self, *roles, reason=None):
        self.changes.append(("add", [r.id for r in roles]))
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.changes.append(("remove", [r.id for r in roles]))
        self.roles = [r for r in self.roles if r not in roles]


class FakeServer:
    """A Discord server whose roles the bot creates, deletes, gives and
    takes. The bot's top role is at position 50; new roles go in at 10.
    Created and deleted role names are recorded; kicks too."""

    def __init__(self, server_id=10, *, can_manage_roles=True):
        self.id = server_id
        self.name = "Example Server"
        self.chunked = True
        self.roles = {}
        self.created, self.deleted, self.kicked = [], [], []
        self.members = []
        self.everyone = FakeRole(self, server_id, "@everyone", 0)
        self.me = SimpleNamespace(top_role=FakeRole(self, 1, "GW2Bot", 50),
                                  guild_permissions=SimpleNamespace(manage_roles=can_manage_roles))
        self.chunk = AsyncMock()

    def role(self, name, position=10, role_id=None):
        role = FakeRole(self, role_id or 100 + len(self.roles), name, position)
        self.roles[role.id] = role
        return role

    def member(self, member_id, *roles, days_on_server=3):
        member = FakeMember(self, member_id, roles, days_on_server)
        self.members.append(member)
        return member

    def add(self, member):
        """Put an existing member (and their roles) on this server."""
        member.guild = self
        if self.everyone not in member.roles:
            member.roles.insert(0, self.everyone)
        for role in member.roles:
            if role is not self.everyone:
                self.roles.setdefault(role.id, role)
        self.members.append(member)
        return member

    def get_role(self, role_id):
        return self.roles.get(role_id)

    def get_member(self, member_id):
        return next((m for m in self.members if m.id == member_id), None)

    async def create_role(self, name, reason=None, color=None):
        self.created.append(name)
        return self.role(name)

    async def kick(self, user, reason=None):
        self.kicked.append(user.id)


class RecordingChannel:
    """A channel, or a user's DMs. Messages it sends are recorded in `sent`
    as (content, embed dict or None, view), with ids from 1001; what
    happens to messages in `edited` / `deleted` / `pinned` / `unpinned`
    (message ids). `existing` are ids of messages already there. Sending
    an embed without embed permission, or anything without send
    permission, raises Forbidden; with `error`, every send raises it."""

    def __init__(self, channel_id=5, guild_id=10, *, existing=(), can_send=True, can_embed=True, error=None):
        self.error = error
        self.id = channel_id
        self.name = f"channel-{channel_id}"
        self.mention = f"<#{channel_id}>"
        self.guild = MagicMock(id=guild_id)
        self.can_send, self.can_embed = can_send, can_embed
        self.sent, self.edited, self.deleted, self.pinned, self.unpinned = [], [], [], [], []
        self.messages = {message_id: self._message(message_id) for message_id in existing}

    def permissions_for(self, member):
        if member is None:
            # Like discord.py, for someone who isn't on the server
            raise AttributeError("'NoneType' object has no attribute '_roles'")
        return SimpleNamespace(send_messages=self.can_send, embed_links=self.can_embed, read_message_history=True,
                               use_external_emojis=True)

    def _message(self, message_id):
        message = MagicMock(id=message_id, pinned=False, created_at=datetime.datetime(2024, 3, 6, 12, tzinfo=UTC))

        def recorder(record, *, deletes=False):
            async def act(*args, **kwargs):
                if message_id not in self.messages:
                    raise _not_found()
                record.append(message_id)
                if deletes:
                    del self.messages[message_id]

            return AsyncMock(side_effect=act)

        message.edit = recorder(self.edited)
        message.delete = recorder(self.deleted, deletes=True)
        message.pin = recorder(self.pinned)
        message.unpin = recorder(self.unpinned)
        return message

    async def send(self, content=None, *, embed=None, view=None, **kwargs):
        if self.error:
            # Something unexpected going wrong
            raise self.error
        if not self.can_send or (embed and not self.can_embed):
            raise _forbidden()
        message = self._message(1001 + len(self.sent))
        self.messages[message.id] = message
        self.sent.append((content, embed.to_dict() if embed else None, view))
        return message

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise _not_found()
        return self.messages[message_id]

    async def history(self, **kwargs):
        return
        yield


def log_file(filename="20240305-200000.zevtc", content=b"EVTC"):
    """A message attachment."""
    return MagicMock(filename=filename, read=AsyncMock(return_value=content))
