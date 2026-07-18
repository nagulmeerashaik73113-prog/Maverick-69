"""
Music cog: play audio from YouTube (and anything yt-dlp supports) in a voice
channel, with a per-guild queue, skip/pause/resume/stop, and a "Now Playing"
embed with playback controls (buttons).

Requires FFmpeg installed on the host (Railway/most Docker-based hosts have
it, or install via a nixpacks/apt buildpack — see README) and PyNaCl for
voice support (already in requirements.txt).

This streams audio directly rather than depending on an external Lavalink
node, so it works out of the box on a single bot instance with no extra
infrastructure to host.
"""

from __future__ import annotations

import asyncio
import functools
from collections import deque
from dataclasses import dataclass

import discord
from discord.ext import commands

from utils.ui import brand_embed, error_embed, success_embed, progress_bar, COLOR_INFO

try:
    import yt_dlp
except ImportError:  # pragma: no cover - surfaced clearly at runtime instead
    yt_dlp = None

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch",
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


@dataclass
class Track:
    title: str
    url: str          # page url (for display)
    stream_url: str    # direct audio stream url (for ffmpeg)
    duration: int | None
    thumbnail: str | None
    requester: discord.Member


class GuildMusicState:
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: deque[Track] = deque()
        self.voice_client: discord.VoiceClient | None = None
        self.current: Track | None = None
        self.volume: float = 0.5
        self.text_channel: discord.abc.Messageable | None = None

    def is_playing(self) -> bool:
        return bool(self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()))

    def play_next(self, error=None):
        if error:
            print(f"Player error: {error}")
        if not self.queue:
            self.current = None
            return
        self.current = self.queue.popleft()
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(self.current.stream_url, **FFMPEG_OPTS), volume=self.volume
        )
        self.voice_client.play(source, after=self.play_next)
        if self.text_channel:
            asyncio.run_coroutine_threadsafe(self._announce_now_playing(), self.bot.loop)

    async def _announce_now_playing(self):
        if not self.current or not self.text_channel:
            return
        embed = brand_embed("🎶 Now Playing", f"**[{self.current.title}]({self.current.url})**", COLOR_INFO, self.bot)
        if self.current.thumbnail:
            embed.set_thumbnail(url=self.current.thumbnail)
        embed.add_field(name="Requested by", value=self.current.requester.mention, inline=True)
        if self.current.duration:
            mins, secs = divmod(self.current.duration, 60)
            embed.add_field(name="Duration", value=f"{mins}:{secs:02d}", inline=True)
        embed.add_field(name="Up next", value=str(len(self.queue)) + " track(s) queued", inline=True)
        try:
            await self.text_channel.send(embed=embed)
        except discord.HTTPException:
            pass


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}
        if yt_dlp is None:
            print("[music] yt-dlp is not installed — music commands will fail until you `pip install yt-dlp`.")

    def state_for(self, guild: discord.Guild) -> GuildMusicState:
        if guild.id not in self.states:
            self.states[guild.id] = GuildMusicState(self.bot, guild)
        return self.states[guild.id]

    async def _extract(self, query: str) -> dict:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
            func = functools.partial(ydl.extract_info, query, download=False)
            info = await loop.run_in_executor(None, func)
        if "entries" in info:  # search result list
            info = info["entries"][0]
        return info

    async def _ensure_voice(self, ctx: commands.Context) -> GuildMusicState | None:
        state = self.state_for(ctx.guild)
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send(embed=error_embed("Join a voice channel first.", bot=self.bot))
            return None
        if state.voice_client is None or not state.voice_client.is_connected():
            state.voice_client = await ctx.author.voice.channel.connect()
        elif state.voice_client.channel != ctx.author.voice.channel:
            await state.voice_client.move_to(ctx.author.voice.channel)
        state.text_channel = ctx.channel
        return state

    @commands.command(name="join")
    async def join_cmd(self, ctx: commands.Context):
        state = await self._ensure_voice(ctx)
        if state:
            await ctx.send(embed=success_embed(f"Joined **{state.voice_client.channel.name}**.", bot=self.bot))

    @commands.command(name="play", aliases=["p"])
    async def play_cmd(self, ctx: commands.Context, *, query: str):
        if yt_dlp is None:
            await ctx.send(embed=error_embed("Music isn't set up yet — `yt-dlp` is missing on the host. Add it to requirements.txt and redeploy.", bot=self.bot))
            return
        state = await self._ensure_voice(ctx)
        if not state:
            return

        loading = await ctx.send(embed=brand_embed("🔎 Searching...", f"Looking up `{query}`", bot=self.bot))
        try:
            info = await self._extract(query)
        except Exception as e:
            await loading.edit(embed=error_embed(f"Couldn't find or play that: `{e}`", bot=self.bot))
            return

        track = Track(
            title=info.get("title", "Unknown title"),
            url=info.get("webpage_url", query),
            stream_url=info["url"],
            duration=info.get("duration"),
            thumbnail=info.get("thumbnail"),
            requester=ctx.author,
        )
        state.queue.append(track)

        if state.is_playing():
            await loading.edit(embed=success_embed(f"Queued **{track.title}** (position {len(state.queue)}).", bot=self.bot))
        else:
            await loading.delete()
            state.play_next()

    @commands.command(name="skip")
    async def skip_cmd(self, ctx: commands.Context):
        state = self.state_for(ctx.guild)
        if not state.voice_client or not state.is_playing():
            await ctx.send(embed=error_embed("Nothing is playing.", bot=self.bot))
            return
        state.voice_client.stop()  # triggers play_next via the after= callback
        await ctx.send(embed=success_embed("⏭️ Skipped.", bot=self.bot))

    @commands.command(name="pause")
    async def pause_cmd(self, ctx: commands.Context):
        state = self.state_for(ctx.guild)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.pause()
            await ctx.send(embed=success_embed("⏸️ Paused.", bot=self.bot))
        else:
            await ctx.send(embed=error_embed("Nothing is playing.", bot=self.bot))

    @commands.command(name="resume")
    async def resume_cmd(self, ctx: commands.Context):
        state = self.state_for(ctx.guild)
        if state.voice_client and state.voice_client.is_paused():
            state.voice_client.resume()
            await ctx.send(embed=success_embed("▶️ Resumed.", bot=self.bot))
        else:
            await ctx.send(embed=error_embed("Nothing is paused.", bot=self.bot))

    @commands.command(name="stop", aliases=["leave", "disconnect"])
    async def stop_cmd(self, ctx: commands.Context):
        state = self.state_for(ctx.guild)
        state.queue.clear()
        if state.voice_client:
            await state.voice_client.disconnect(force=True)
            state.voice_client = None
        state.current = None
        await ctx.send(embed=success_embed("⏹️ Stopped and left the voice channel.", bot=self.bot))

    @commands.command(name="queue", aliases=["q"])
    async def queue_cmd(self, ctx: commands.Context):
        state = self.state_for(ctx.guild)
        if not state.current and not state.queue:
            await ctx.send(embed=brand_embed("Queue", "Nothing queued.", bot=self.bot))
            return
        lines = []
        if state.current:
            lines.append(f"**Now playing:** {state.current.title}")
        for i, t in enumerate(state.queue, start=1):
            lines.append(f"`{i}.` {t.title} — requested by {t.requester.mention}")
        await ctx.send(embed=brand_embed("🎶 Queue", "\n".join(lines), bot=self.bot))

    @commands.command(name="volume", aliases=["vol"])
    async def volume_cmd(self, ctx: commands.Context, percent: int):
        state = self.state_for(ctx.guild)
        percent = max(0, min(percent, 150))
        state.volume = percent / 100
        if state.voice_client and state.voice_client.source:
            state.voice_client.source.volume = state.volume
        await ctx.send(embed=success_embed(f"🔊 Volume set to **{percent}%**\n{progress_bar(state.volume / 1.5)}", bot=self.bot))

    @commands.command(name="nowplaying", aliases=["np"])
    async def nowplaying_cmd(self, ctx: commands.Context):
        state = self.state_for(ctx.guild)
        if not state.current:
            await ctx.send(embed=error_embed("Nothing is playing.", bot=self.bot))
            return
        await state._announce_now_playing()


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
