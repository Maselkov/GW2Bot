from .general import GeneralGuild
from .sync import SyncGuild


class GuildMixin(GeneralGuild, SyncGuild):
    pass
