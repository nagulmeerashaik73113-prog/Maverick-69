"""
All-in-one Discord Bot
----------------------
AI chat, continuous moderation, anti-nuke protection, and music — one bot,
one entry point. Loads config, sets up the bot, and keeps it alive.
"""

import os
import asyncio
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

from keep_alive import keep_alive

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing. Set it in your .env or host's environment variables.")

intents = discord.Intents.default()
intents.message_content = True  # required to read message text for AI replies + automod
intents.members = True          # required for join/leave events, anti-nuke, moderation
intents.moderation = True       # ban/unban events for anti-nuke
intents.voice_states = True     # required for music playback

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

INITIAL_COGS = [
    "cogs.ai_chat",
    "cogs.admin",
    "cogs.moderation",
    "cogs.antinuke",
    "cogs.music",
    "cogs.help_menu",
]


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    log.info(f"Connected to {len(bot.guilds)} server(s).")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name=f"your server 🛡️ | {COMMAND_PREFIX}help")
    )


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # Central, quiet error handling so a bad command never dumps a traceback in chat.
    from utils.ui import error_embed

    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.send(embed=error_embed(str(error) or "You don't have permission to do that.", bot=bot))
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=error_embed(f"Missing argument: `{error.param.name}`. Check `{COMMAND_PREFIX}help {ctx.command}`.", bot=bot))
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(embed=error_embed(f"Couldn't understand one of your arguments: {error}", bot=bot))
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(embed=error_embed(f"Slow down — try again in {error.retry_after:.1f}s.", bot=bot))
        return

    log.exception(f"Unhandled error in command {ctx.command}: {error}")
    await ctx.send(embed=error_embed("Something went wrong running that command. The host has been logged.", bot=bot))


async def load_cogs():
    for cog in INITIAL_COGS:
        try:
            await bot.load_extension(cog)
            log.info(f"Loaded cog: {cog}")
        except Exception as e:
            log.exception(f"Failed to load cog {cog}: {e}")


async def main():
    # Flask keep-alive server (useful for Replit/UptimeRobot pings;
    # harmless no-op style ping endpoint on other hosts too)
    keep_alive()

    async with bot:
        await load_cogs()
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
