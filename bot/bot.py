import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_BOT_TOKEN environment variable not found.")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

if sys.platform != "win32" and not discord.opus.is_loaded():
    try:
        discord.opus.load_opus("libopus.so.0")
    except OSError:
        logging.warning("Could not load libopus; voice playback will not work.")

class KanderliBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await load_cogs(self)
        self.loop.create_task(self._initial_sync())

    async def _initial_sync(self) -> None:
        await self.wait_until_ready()
        assert self.user is not None
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.sync_app_commands()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._sync_guild_commands(guild)

    async def sync_app_commands(self) -> None:

        assert self.application_id is not None
        await self.http.bulk_upsert_global_commands(self.application_id, [])

        for guild in self.guilds:
            await self._sync_guild_commands(guild)

    async def _sync_guild_commands(self, guild: discord.Guild) -> None:
        self.tree.copy_global_to(guild=guild)
        guild_synced = await self.tree.sync(guild=guild)
        logging.info(
            "Synced %d command(s) to guild %s (%s)",
            len(guild_synced),
            guild.name,
            guild.id,
        )


bot = KanderliBot()


async def load_cogs(bot_instance: commands.Bot) -> None:
    cog_dir = Path(__file__).parent / "cogs"

    if not cog_dir.exists():
        raise RuntimeError(f"Cog directory does not exist: {cog_dir}")

    for cog_file in cog_dir.glob("*.py"):
        if cog_file.stem.startswith("_"):
            continue

        cog_name = f"cogs.{cog_file.stem}"
        try:
            await bot_instance.load_extension(cog_name)
            logging.info("Loaded cog: %s", cog_name)
        except Exception:
            logging.exception("Failed to load cog: %s", cog_name)



async def main():
    async with bot:
        await bot.start(TOKEN)


logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":
    asyncio.run(main())
    
