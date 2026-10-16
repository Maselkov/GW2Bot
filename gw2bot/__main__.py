"""Run the bot: python -m gw2bot"""
import asyncio
import logging
import logging.handlers
import os
import sys

from .bot import GW2Bot
from .config import ConfigError, Settings


def setup_logging(settings):
    formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("discord.http").setLevel(logging.WARNING)

    os.makedirs(settings.log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(settings.log_dir, "gw2bot.log"),
        maxBytes=10 * 1024 * 1024,
        encoding="utf-8",
        backupCount=5,
    )
    file_handler.setFormatter(formatter)
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)


async def run(settings):
    async with GW2Bot(settings) as bot:
        await bot.start(settings.token)


def main():
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        sys.exit(f"Configuration error: {e}")
    setup_logging(settings)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
