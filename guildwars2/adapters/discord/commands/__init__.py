"""Auto-discovery and registration for Discord command handlers.

Preferred usage options:

- Define commands with `@discord.app_commands.command` in modules under this
    package; the loader will import submodules and add any `app_commands.Command`
    or `app_commands.Group` objects it finds to the bot's command tree.

Legacy mode: modules can also export a `register(cog)` function, which will
be invoked to perform custom registration if needed.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import (
    Callable,
    Iterable,
    Optional,
    TypeVar,
    ParamSpec,
    Concatenate,
    Any,
    cast,
    Coroutine,
)

from discord import app_commands, Interaction
import functools
import inspect


def _iter_submodules(pkg_name: str) -> Iterable[str]:
    pkg = importlib.import_module(pkg_name)
    if not hasattr(pkg, "__path__"):
        return []
    for mod in pkgutil.walk_packages(pkg.__path__, pkg_name + "."):
        yield mod.name


def register_all(cog) -> None:
    """Find and register all command modules under this package.

    Command modules should expose `register(cog)` or `bind(cog)`.
    """
    base = __name__  # e.g., guildwars2.adapters.discord.commands
    for name in list(_iter_submodules(base)):
        try:
            mod: ModuleType = importlib.import_module(name)
        except Exception:
            continue
        registrar: Callable | None = None
        for attr in ("register", "bind"):
            fn = getattr(mod, attr, None)
            if callable(fn):
                registrar = fn
                break
        if registrar:
            try:
                registrar(cog)
            except Exception:
                # Ignore failures to avoid breaking other commands
                continue

        # Determine target group for this module, if any
        group_target = None
        group_name = getattr(mod, "__group__", None)
        if isinstance(group_name, str) and group_name:
            group_desc = getattr(mod, "__group_description__", None)
            try:
                group_target = ensure_group(cog, group_name, description=group_desc)
            except Exception:
                group_target = None
        else:
            # Fallback: if module is part of a package that exposes a 'group', use it
            try:
                pkg_name = mod.__package__
                if pkg_name:
                    pkg = importlib.import_module(pkg_name)
                    pkg_group = getattr(pkg, "group", None)
                    if isinstance(pkg_group, app_commands.Group):
                        # Make sure tree has it and cache on cog
                        try:
                            cog.bot.tree.add_command(pkg_group)
                        except Exception:
                            pass
                        group_target = pkg_group
            except Exception:
                group_target = None

        # Direct app_commands discovery: add commands and groups declared in module
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            # Skip the exported package-level group attribute itself
            if attr_name == "group" and isinstance(obj, app_commands.Group):
                continue
            try:
                if isinstance(obj, app_commands.Command):
                    if group_target:
                        try:
                            group_target.add_command(obj)
                        except Exception:
                            pass
                    else:
                        cog.bot.tree.add_command(obj)
                elif isinstance(obj, app_commands.Group):
                    if group_target:
                        # Avoid adding the package-level group to itself
                        if obj is group_target:
                            continue
                        try:
                            group_target.add_command(obj)
                        except Exception:
                            pass
                    else:
                        cog.bot.tree.add_command(obj)
            except Exception:
                # Ignore duplicates or timing issues
                continue


def ensure_group(
    cog, name: str, description: Optional[str] = None
) -> app_commands.Group:
    """Ensure an app_commands.Group exists on the Cog and in the command tree.

    - Reuses an attribute on the cog named `<name>_group` if present and valid
    - Otherwise tries to fetch an existing group from the command tree
    - If not found, creates and registers a new group and caches it on the cog
    """
    attr = f"{name}_group"
    existing = getattr(cog, attr, None)
    if isinstance(existing, app_commands.Group):
        return existing
    # Try to find an existing group in the tree
    try:
        cmd = cog.bot.tree.get_command(name=name)
        if isinstance(cmd, app_commands.Group):
            setattr(cog, attr, cmd)
            return cmd
    except Exception:
        pass
    # Create a new group and add it to the tree
    group = app_commands.Group(
        name=name, description=description or f"{name.title()} commands"
    )
    try:
        cog.bot.tree.add_command(group)
    except Exception:
        # If already exists, fetch and reuse
        try:
            cmd = cog.bot.tree.get_command(name=name)
            if isinstance(cmd, app_commands.Group):
                group = cmd
        except Exception:
            pass
    setattr(cog, attr, group)
    return group


P = ParamSpec("P")
T = TypeVar("T")


def with_cog(
    cog_name: str = "GuildWars2",
) -> Callable[
    [Callable[Concatenate[Any, Interaction[Any], P], Coroutine[Any, Any, T]]],
    Callable[Concatenate[Interaction[Any], P], Coroutine[Any, Any, T]],
]:
    """Type-safe decorator to inject the named Cog into an app_command callback.

    Usage:
        @app_commands.command(name="foo")
        @with_cog()
        async def foo(cog, interaction, ...): ...

    This transforms a function of shape (cog, interaction, *args) -> Awaitable[T]
    into (interaction, *args) -> Awaitable[T] so app_commands sees the correct
    Interaction-first signature. Keep this decorator closest to the function.
    """

    def _decorator(
        func: Callable[Concatenate[Any, Interaction[Any], P], Coroutine[Any, Any, T]],
    ) -> Callable[Concatenate[Interaction[Any], P], Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def _wrapped(
            interaction: Interaction[Any], *args: P.args, **kwargs: P.kwargs
        ) -> T:
            get = getattr(interaction.client, "get_cog", None)
            cog = get(cog_name) if callable(get) else None
            if not cog:
                try:
                    await interaction.response.send_message(
                        f"{cog_name} cog is not loaded.", ephemeral=True
                    )
                except Exception:
                    pass
                return cast(T, None)
            return await func(cog, interaction, *args, **kwargs)

        # Adjust visible signature: drop the first param (cog)
        try:
            orig_sig = inspect.signature(func)
            params = list(orig_sig.parameters.values())
            if params:
                params = params[1:]
            new_sig = inspect.Signature(
                parameters=params, return_annotation=orig_sig.return_annotation
            )
            setattr(_wrapped, "__signature__", new_sig)
        except Exception:
            pass

        return _wrapped

    return _decorator
