# GW2Bot Architecture (Target)

This document proposes a structure that keeps a single exported Cog class for discord.py while removing the tight mixin coupling. The key ideas:

- Separate layers:
  - `adapters/discord`: Cogs, command handlers, interaction views
  - `core/api`: GW2 HTTP API client and domain models
  - `core/services`: stateless or light state application logic (formerly mixin methods)
  - `data`: persistence, caching, migrations
  - `shared`: utilities, constants, DTOs, errors
- Use dependency injection: a light-weight service container wires services together and hands them to the Cog.
- Provide a Facade `GuildWars2` Cog that composes services instead of inheriting mixins.
- Keep public behavior and command signatures identical while migrating incrementally feature-by-feature.

## Why change?

- Mixins hide dependencies and create fragile diamond inheritance chains.
- Cross-references are hard: IDEs can’t auto-navigate, type hints get muddy.
- Testing is painful because behavior is spread across classes by inheritance.

Composition via services:

- Each service exposes a clear contract, injected with its dependencies (api client, db, caches).
- The Cog delegates to services; it becomes thin, focused on Discord concerns.
- Easy to test a service in isolation; easy to reuse logic from other entry points.

## Proposed layout

```
guildwars2/
  adapters/
    discord/
      __init__.py
      cog.py            # GuildWars2 Cog (the facade)
      views.py          # UI components
  core/
    __init__.py
    api_client.py      # async GW2 API (httpx/aiohttp)
    models.py          # pydantic/dataclasses (optional)
    services/
      __init__.py
      account.py
      raids.py
      items.py
      ...
  data/
    __init__.py
    repositories.py    # Mongo abstractions
    cache.py
  shared/
    __init__.py
    errors.py          # your existing exceptions
    settings.py
    utils/
      chat.py
      db.py
```

Your existing modules can be migrated gradually:

- Move read-only helpers to `shared/utils` (keep import shims to avoid breaks).
- Wrap Mongo calls inside `data/repositories.py` and inject those into services.
- Move GW2 API methods from `ApiMixin` to `core/api_client.py` as `GW2ApiClient`.
- For each feature mixin (e.g., `AccountMixin`):
  1) Extract discord-free logic into a service: `AccountService`.
  2) In the Cog, keep the `@app_commands` function but delegate to the service.

## The Facade Cog

The Cog maintains the module contract for discord.py (still a single class exported), but composition replaces inheritance:

- Create `ServiceContainer` that builds and caches service singletons.
- `GuildWars2` Cog receives the container and pulls services it needs.
- Cog methods stay in one class, but the logic lives in services.

## Incremental migration plan

1. Introduce scaffolding (no behavior change):
   - `core/api_client.py` (wrap existing `call_api`, `call_multiple`, `cache_result`).
   - `data/repositories.py` with thin wrappers over `self.db` usage.
   - `adapters/discord/cog.py` new Cog that composes services but exports the same setup entry point, or keep current `setup` and use container internally.
2. Migrate one feature as a slice ("walking skeleton"):
   - Extract a small command, e.g., `/account` summary, into `AccountService`.
   - The Cog calls `account_service.get_summary(user)` and formats the embed.
3. Repeat per feature:
   - When a feature is migrated, delete the mixin inheritance for that part.
4. Remove mixins entirely when the last feature moves.

## Dependency conventions

- Services depend only on `api_client`, `repositories`, and `time/clock` helpers.
- Services should not import Discord. Return plain data objects or dicts; Cog renders embeds.
- Views and long-running tasks (tasks.loop) live in adapters/discord; they call services.

## Example contracts

- GW2ApiClient
  - `async get(endpoint, *, user=None, key=None, schema_version=None) -> dict|list`
  - Raises domain errors from `shared/errors.py` (your existing exceptions)
- AccountService
  - `async get_account(user) -> Account` (or dict)
  - `async get_killproof(user) -> KillProofSummary`
- ItemsService
  - `async find_items(user, ids) -> Dict[str,int]`

## Testing

- Unit test services with fake api_client and fake repositories.
- Keep a couple of integration tests that spin up the Cog with a real container and a mock Discord interaction.

## Typing and tooling

- Add typing to the service interfaces; enable mypy (optional) for clarity.
- Keep tenacity retry in the API client; keep httpx or aiohttp session management in the container.

## Backwards compatibility

- Keep `async def setup(bot)` exporting the same Cog class name so your external loader doesn’t change.
- Provide import shims for `guildwars2.utils.chat` and `utils.db` while moving code.

## FAQ

- Why not multiple cogs? You can split into multiple cogs later. Keeping one facade Cog first avoids breaking the plugin consumer if it expects a single class.
- Long-running tasks? Put them in the Cog but move business logic to services; only the task loop and scheduling remain in the Cog.
- Where to store shared state? Prefer repositories and caches; avoid global singletons. The container can hold process-wide clients (http, db).
