"""
Shared visual identity for the bot: colors, branded embeds, and small
"animated" UI touches (progress bars, loading messages that edit themselves,
paginators with buttons). Discord bots can't do real frame animation outside
of GIF thumbnails, so "animated" here means responsive, motion-feeling UI:
edited messages, progress bars, button interactions, timed transitions.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

import discord

# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------
COLOR_PRIMARY = 0x5865F2   # blurple
COLOR_SUCCESS = 0x57F287
COLOR_WARNING = 0xFEE75C
COLOR_DANGER = 0xED4245
COLOR_INFO = 0x5865F2

FOOTER_ICON = None  # set to your bot's avatar URL if you want a footer icon


def brand_embed(title: str, description: str = "", color: int = COLOR_PRIMARY, bot: discord.Client | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if bot and bot.user:
        embed.set_footer(text=bot.user.name, icon_url=bot.user.display_avatar.url)
    return embed


def success_embed(description: str, title: str = "✅ Done", bot=None) -> discord.Embed:
    return brand_embed(title, description, COLOR_SUCCESS, bot)


def error_embed(description: str, title: str = "❌ Error", bot=None) -> discord.Embed:
    return brand_embed(title, description, COLOR_DANGER, bot)


def warning_embed(description: str, title: str = "⚠️ Warning", bot=None) -> discord.Embed:
    return brand_embed(title, description, COLOR_WARNING, bot)


def progress_bar(percent: float, length: int = 16) -> str:
    """Text progress bar, e.g. used for song position / loading states."""
    percent = max(0.0, min(1.0, percent))
    filled = round(length * percent)
    return "▰" * filled + "▱" * (length - filled)


async def loading_message(channel: discord.abc.Messageable, text: str = "Working"):
    """
    Sends a message and animates a few loading frames on it by editing.
    Returns the message so the caller can do a final edit with the real result.
    Use like:
        msg = await loading_message(ctx.channel, "Searching")
        ... do work ...
        await msg.edit(embed=final_embed)
    """
    frames = ["⏳", "🔄", "⌛"]
    msg = await channel.send(f"{frames[0]} {text}...")
    for frame in frames[1:]:
        await asyncio.sleep(0.5)
        try:
            await msg.edit(content=f"{frame} {text}...")
        except discord.HTTPException:
            break
    return msg


class Paginator(discord.ui.View):
    """Button-driven embed paginator (Prev / Page x/y / Next / Stop)."""

    def __init__(self, embeds: Sequence[discord.Embed], author_id: int, timeout: float = 90):
        super().__init__(timeout=timeout)
        self.embeds = list(embeds)
        self.author_id = author_id
        self.index = 0
        self._sync_labels()

    def _sync_labels(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "page":
                child.label = f"{self.index + 1}/{len(self.embeds)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This menu isn't yours — run the command yourself.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index - 1) % len(self.embeds)
        self._sync_labels()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True, custom_id="page")
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index + 1) % len(self.embeds)
        self._sync_labels()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="✖", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class ConfirmView(discord.ui.View):
    """Yes/No confirmation used before destructive actions (bans, purges, etc.)."""

    def __init__(self, author_id: int, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command author can confirm this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
