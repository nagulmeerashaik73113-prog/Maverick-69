"""
Central place for "is this person allowed to do this" checks.

Keeping all of this in one module — instead of scattering permission logic
across cogs — is itself a security measure: there's exactly one place to
audit or tighten. Every destructive command (ban, antinuke config, etc.)
should route through one of these.
"""

from __future__ import annotations

import os

import discord
from discord.ext import commands

from utils.storage import guild_config

# Bot-owner IDs (comma-separated in env) always pass every check — this is
# for the person(s) hosting the bot, not per-server admins.
_OWNER_IDS = {int(x) for x in os.getenv("BOT_OWNER_IDS", "").replace(" ", "").split(",") if x}


def is_bot_owner(user_id: int) -> bool:
    return user_id in _OWNER_IDS


def is_server_owner(member: discord.Member) -> bool:
    return member.guild.owner_id == member.id


def has_mod_role(member: discord.Member) -> bool:
    cfg = guild_config.get(member.guild.id, {})
    mod_role_ids = set(cfg.get("mod_role_ids", []))
    if not mod_role_ids:
        return member.guild_permissions.moderate_members or member.guild_permissions.kick_members
    return any(role.id in mod_role_ids for role in member.roles)


def has_admin_role(member: discord.Member) -> bool:
    cfg = guild_config.get(member.guild.id, {})
    admin_role_ids = set(cfg.get("admin_role_ids", []))
    if member.guild_permissions.administrator or is_server_owner(member):
        return True
    return any(role.id in admin_role_ids for role in member.roles)


def can_target(actor: discord.Member, target: discord.Member) -> tuple[bool, str]:
    """Role-hierarchy + safety checks before a mod action lands on `target`."""
    if target.id == actor.guild.owner_id:
        return False, "You can't take moderation action against the server owner."
    if target.id == actor.id:
        return False, "You can't target yourself."
    if target.bot and target.id == actor.guild.me.id:
        return False, "I can't target myself."
    if actor.top_role <= target.top_role and actor.id != actor.guild.owner_id:
        return False, "You can't act on someone with an equal or higher role than you."
    if actor.guild.me.top_role <= target.top_role:
        return False, "My role is below (or equal to) theirs — move my role higher in Server Settings."
    return True, ""


def mod_check():
    """Decorator: command requires mod role or admin/owner."""
    async def predicate(ctx: commands.Context) -> bool:
        if is_bot_owner(ctx.author.id):
            return True
        if not isinstance(ctx.author, discord.Member):
            return False
        if has_admin_role(ctx.author) or has_mod_role(ctx.author):
            return True
        raise commands.CheckFailure("You need a moderator role to use this command.")
    return commands.check(predicate)


def admin_check():
    """Decorator: command requires admin role, server owner, or bot owner."""
    async def predicate(ctx: commands.Context) -> bool:
        if is_bot_owner(ctx.author.id):
            return True
        if not isinstance(ctx.author, discord.Member):
            return False
        if has_admin_role(ctx.author):
            return True
        raise commands.CheckFailure("You need an administrator role to use this command.")
    return commands.check(predicate)


def owner_check():
    """Decorator: command requires the server owner or the bot's host."""
    async def predicate(ctx: commands.Context) -> bool:
        if is_bot_owner(ctx.author.id):
            return True
        if isinstance(ctx.author, discord.Member) and is_server_owner(ctx.author):
            return True
        raise commands.CheckFailure("Only the server owner can use this command.")
    return commands.check(predicate)
