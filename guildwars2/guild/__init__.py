from .general import GeneralGuild
from .sync import GuildSync


class GuildMixin(GeneralGuild, GuildSync):
    pass
