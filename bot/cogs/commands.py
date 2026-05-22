import asyncio
import logging
from collections import deque
from dataclasses import dataclass

# from random import choice
from typing import Deque, Dict, Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

_ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)


@dataclass
class Track:
    title: str
    url: str  # streamable URL
    webpage_url: str
    requester_id: int


async def _extract(query: str) -> Track:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        None, lambda: _ytdl.extract_info(query, download=False)
    )
    if data is None:
        raise RuntimeError("No results")
    if "entries" in data:
        data = data["entries"][0]
    return Track(
        title=data.get("title", "Unknown"),
        url=data["url"],
        webpage_url=data.get("webpage_url", ""),
        requester_id=0,
    )


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.queues: Dict[int, Deque[Track]] = {}
        self.current: Dict[int, Optional[Track]] = {}

    def _queue(self, guild_id: int) -> Deque[Track]:
        return self.queues.setdefault(guild_id, deque())

    async def _ensure_voice(
        self, interaction: discord.Interaction
    ) -> Optional[discord.VoiceClient]:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Music commands only work in a server.", ephemeral=True
            )
            return None
        voice_state = interaction.user.voice
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "You need to be in a voice channel first.", ephemeral=True
            )
            return None
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc is None:
            vc = await voice_state.channel.connect()
        elif vc.channel != voice_state.channel:
            await vc.move_to(voice_state.channel)
        return vc  # type: ignore[return-value]
    
    async def _ensure_voice_after_defer(
        self, interaction: discord.Interaction
    ) -> Optional[discord.VoiceClient]:
        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Music commands only work in a server.")
            return None
        voice_state = interaction.user.voice
        if voice_state is None or voice_state.channel is None:
            await interaction.followup.send("You need to be in a voice channel first.")
            return None
        guild = interaction.guild
        assert guild is not None
        vc = guild.voice_client
        if vc is None:
            vc = await voice_state.channel.connect()
        elif vc.channel != voice_state.channel:
            await vc.move_to(voice_state.channel)
        return vc  # type: ignore[return-value]

    @app_commands.command(name="play", description="Play a song from a URL or search.")
    @app_commands.describe(query="A URL or search query")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        vc = await self._ensure_voice_after_defer(interaction)
        if vc is None:
            return
        try:
            track = await _extract(query)
        except Exception as exc:
            logging.exception("Failed to extract track")
            await interaction.followup.send(f"Failed to load track: {exc}")
            return
        track.requester_id = interaction.user.id
        guild = interaction.guild
        assert guild is not None
        self._queue(guild.id).append(track)
        if not vc.is_playing() and not vc.is_paused():
            self._play_next(guild)
            await interaction.followup.send(f"Now playing: **{track.title}**")
        else:
            await interaction.followup.send(f"Queued: **{track.title}**")
    
    def _play_next(self, guild: discord.Guild) -> None:
        queue = self._queue(guild.id)
        if not queue:
            self.current[guild.id] = None
            return
        track = queue.popleft()
        self.current[guild.id] = track
        vc = guild.voice_client
        if vc is None:
            return
        source = discord.FFmpegPCMAudio(track.url, **FFMPEG_OPTS)

        def _after(error: Optional[Exception]) -> None:
            if error:
                logging.exception("Playback error", exc_info=error)
            fut = asyncio.run_coroutine_threadsafe(
                self._after_play(guild), self.bot.loop
            )
            try:
                fut.result()
            except Exception:
                logging.exception("Failed to advance queue")

        vc.play(source, after=_after)

    async def _after_play(self, guild: discord.Guild) -> None:
        self._play_next(guild)

    @app_commands.command(name="pause", description="Pause the current track.")
    async def pause(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Paused.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Nothing is playing.", ephemeral=True
            )

    @app_commands.command(name="resume", description="Resume playback.")
    async def resume(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Resumed.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Nothing is paused.", ephemeral=True
            )

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # triggers after-callback -> next track
            await interaction.response.send_message("Skipped.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Nothing to skip.", ephemeral=True
            )

    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    async def stop(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        self._queue(guild.id).clear()
        self.current[guild.id] = None
        vc = guild.voice_client
        if vc:
            vc.stop()
        await interaction.response.send_message(
            "Stopped and cleared queue.", ephemeral=True
        )

    @app_commands.command(name="queue", description="Show the current queue.")
    async def queue(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return
        current = self.current.get(guild.id)
        upcoming = list(self._queue(guild.id))
        lines = []
        if current:
            lines.append(f"**Now playing:** {current.title}")
        if upcoming:
            lines.append("**Up next:**")
            for i, track in enumerate(upcoming[:10], start=1):
                lines.append(f"{i}. {track.title}")
            if len(upcoming) > 10:
                lines.append(f"...and {len(upcoming) - 10} more")
        if not lines:
            lines.append("Queue is empty.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class Commands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.original_channels: Dict[int, discord.VoiceChannel] = {}

    @app_commands.command(name="ping", description="Responds with Pong!")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!", ephemeral=True)

    @app_commands.command(name="join", description="Join your voice channel.")
    async def join(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command only works in a server.", ephemeral=True
            )
            return
        voice_state = interaction.user.voice
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "You need to be in a voice channel first.", ephemeral=True
            )
            return
        guild = interaction.guild
        assert guild is not None
        vc = guild.voice_client
        if vc is None:
            vc = await voice_state.channel.connect()
        elif vc.channel != voice_state.channel:
            await vc.move_to(voice_state.channel)
        await interaction.response.send_message(
            f"Joined **{voice_state.channel.name}**.", ephemeral=True
        )

    @app_commands.command(name="leave", description="Leave the voice channel.")
    async def leave(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or guild.voice_client is None:
            await interaction.response.send_message(
                "I'm not in a voice channel.", ephemeral=True
            )
            return
        await guild.voice_client.disconnect(force=False)
        music = self.bot.get_cog("Music")
        if isinstance(music, Music):
            music.queues.pop(guild.id, None)
            music.current.pop(guild.id, None)
        await interaction.response.send_message("Disconnected.", ephemeral=True)
    
    # @app_commands.command(name="cibálás", description="Move a user to a random voice channel and back.")
    # async def cibalas(self, interaction: discord.Interaction, user: discord.Member) -> None:
    #     guild = interaction.guild
    #     if guild is None:
    #         await interaction.response.send_message(
    #             "This command only works in a server.", ephemeral=True
    #         )
    #         return
    #     if user.voice is None or user.voice.channel is None:
    #         await interaction.response.send_message(
    #             f"{user.mention} is not in a voice channel!", ephemeral=True
    #         )
    #         return

    #     current_channel = user.voice.channel
    #     voice_channels = [ch for ch in guild.voice_channels if ch != current_channel]
    #     if not voice_channels:
    #         await interaction.response.send_message(
    #             "There's only one voice channel in this server!", ephemeral=True
    #         )
    #         return
        
    #     random_channel = choice(voice_channels)
    #     self.original_channels[user.id] = current_channel
    #     try:
    #         await user.move_to(random_channel)
    #         await asyncio.sleep(1)
    #         await user.move_to(current_channel)

    #     finally:
    #         self.original_channels.pop(user.id, None)

    #     await interaction.response.send_message(
    #         f"{user.mention} megcibálva."
    #     )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
    await bot.add_cog(Commands(bot))
