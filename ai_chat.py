"""
AI auto-reply: responds when @mentioned, replied-to, or inside a configured
"AI channel", using the Anthropic API. Keeps a short rolling memory per
channel and applies a per-user cooldown to avoid spam/API overuse.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands
from anthropic import AsyncAnthropic

from utils.ui import brand_embed, error_embed

AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-6")
SYSTEM_PROMPT = os.getenv("AI_SYSTEM_PROMPT", "You are a helpful, friendly Discord server assistant. Keep replies concise and casual.")
MAX_HISTORY_TURNS = int(os.getenv("AI_MAX_HISTORY_TURNS", "10"))
USER_COOLDOWN_SECONDS = float(os.getenv("AI_USER_COOLDOWN_SECONDS", "5"))
AI_CHANNEL_IDS = {int(x) for x in os.getenv("AI_CHANNEL_IDS", "").replace(" ", "").split(",") if x}

client = AsyncAnthropic() if os.getenv("ANTHROPIC_API_KEY") else None


class AIChat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.history: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY_TURNS * 2))
        self.last_reply: dict[int, float] = defaultdict(float)

    def _on_cooldown(self, user_id: int) -> bool:
        now = time.time()
        if now - self.last_reply[user_id] < USER_COOLDOWN_SECONDS:
            return True
        self.last_reply[user_id] = now
        return False

    async def call_ai(self, channel_id: int, prompt: str) -> str:
        if client is None:
            return "AI chat isn't configured — ask the bot host to set `ANTHROPIC_API_KEY`."
        history = self.history[channel_id]
        messages = list(history) + [{"role": "user", "content": prompt}]
        response = await client.messages.create(
            model=AI_MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        reply = "".join(block.text for block in response.content if block.type == "text").strip()
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": reply})
        return reply or "..."

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        is_mentioned = self.bot.user in message.mentions
        is_reply_to_bot = False
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            is_reply_to_bot = message.reference.resolved.author.id == self.bot.user.id
        is_ai_channel = message.channel.id in AI_CHANNEL_IDS

        if not (is_mentioned or is_reply_to_bot or is_ai_channel):
            return

        if self._on_cooldown(message.author.id):
            return

        content = message.content
        for mention in message.mentions:
            content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
        content = content.strip()
        if not content:
            return

        async with message.channel.typing():
            try:
                reply = await self.call_ai(message.channel.id, content)
            except Exception as e:
                await message.reply(embed=error_embed(f"AI request failed: `{e}`", bot=self.bot))
                return

        if len(reply) > 1900:
            reply = reply[:1900] + "…"
        await message.reply(reply, mention_author=False)

    @commands.command(name="ask")
    async def ask_cmd(self, ctx: commands.Context, *, question: str):
        if self._on_cooldown(ctx.author.id):
            await ctx.send(embed=error_embed("Slow down a bit — try again in a few seconds.", bot=self.bot))
            return
        async with ctx.typing():
            try:
                reply = await self.call_ai(ctx.channel.id, question)
            except Exception as e:
                await ctx.send(embed=error_embed(f"AI request failed: `{e}`", bot=self.bot))
                return
        if len(reply) > 1900:
            reply = reply[:1900] + "…"
        await ctx.reply(reply, mention_author=False)

    @commands.command(name="reset")
    async def reset_cmd(self, ctx: commands.Context):
        self.history[ctx.channel.id].clear()
        await ctx.send(embed=brand_embed("🧠 Memory Cleared", "This channel's AI conversation memory has been reset.", bot=self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChat(bot))
