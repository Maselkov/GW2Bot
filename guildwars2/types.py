from __future__ import annotations

from typing import Any, Mapping, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .core.container import ServiceContainer
else:  # pragma: no cover - only for type checkers
    ServiceContainer = Any  # type: ignore


class GuildWars2Cog(Protocol):
    """Protocol describing the minimal surface we use from the GW2 Cog.

    This enables editor autocomplete in command modules without importing
    the actual Cog type (avoids circular imports during runtime).
    """

    container: ServiceContainer
    db: Any
    gamedata: Mapping[str, Any]
    bot: Any

    async def get_embed_color(self, ctx) -> int: ...

    def get_emoji(
        self, interaction, name: str, *, fallback: bool = False, fallback_fmt: str = ""
    ) -> str: ...

    # Common helpers present on the Cog used throughout commands
    async def call_api(self, *args: Any, **kwargs: Any) -> Any: ...
    async def fetch_key(self, *args: Any, **kwargs: Any) -> Any: ...
    def check_emoji_permission(self, interaction: Any) -> bool: ...
    def format_age(self, seconds: int, short: bool = False) -> str: ...
    async def get_world_name(self, world_id: int) -> str: ...
