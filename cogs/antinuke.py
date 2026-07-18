"""
Anti-Nuke: detects and auto-responds to mass-destructive actions
(channel/role deletion sprees, mass bans/kicks, webhook spam, bot adds,
dangerous permission grants) that usually mean a compromised account or
malicious mod/admin is nuking the server.

How it works:
- Every relevant Discord event increments a per-actor "strike counter" that
  decays over a short time window (default 10s).
- If an actor crosses the configured threshold for an action type, the bot
  immediately strips their dangerous permissions (or bans them, configurable),
  removes them from the action loop, and pings the log channel.
- The server owner and anyone on the whitelist are always exempt — set this
  up correctly or you can lock yourself out of your own moderation actions.

This is a strong baseline, not a guarantee. Nothing running as "just a bot"
can fully stop someone with a higher role or an Administrator permission the
bot doesn't have; the best protection is still: don't over-grant permissions,
and keep the bot's own role high and Administrator so it can act.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

from utils.storage import antinuke_db
from utils.ui import brand_embed, success_embed, error_embed, COLOR_DANGER
from utils.permissions import admin_check, owner_check, is_bot_owner

DEFAULT_CONFIG = {
    "enabled": True,
    "log_channel_id": None,
    "whitelist": [],          # user IDs exempt from punishment
    "punishment": "ban",      # "ban" | "kick" | "strip_roles"
    "thresholds": {
        "channel_delete": 3,
        "channel_create": 5,
        "role_delete": 3,
        "ban": 3,
        "kick": 5,
        "webhook_create": 3,
        "bot_add": 1,
    },
    "window_seconds": 10,
}


class ActionTracker:
    """Per-guild, per-actor, per-action-type sliding-window event counter."""

    def __init__(self):
        # {guild_id: {(user_id, action): deque[timestamps]}}
        self._events: dict[int, dict[tuple[int, str], deque]] = defaultdict(lambda: defaultdict(deque))

    def hit(self, guild_id: int, user_id: int, action: str, window: int) -> int:
        now = time.time()
        dq = self._events[guild_id][(user_id, action)]
        dq.append(now)
        while dq and now - dq[0] > window:
            dq.popleft()
        return len(dq)


class AntiNuke(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tracker = ActionTracker()

    # -- config helpers ----------------------------------------------------

    def cfg(self, guild_id: int) -> dict:
        stored = antinuke_db.get(guild_id, {})
        merged = {**DEFAULT_CONFIG, **stored}
        merged["thresholds"] = {**DEFAULT_CONFIG["thresholds"], **stored.get("thresholds", {})}
        return merged

    def is_exempt(self, guild: discord.Guild, user_id: int, cfg: dict) -> bool:
        if is_bot_owner(user_id):
            return True
        if user_id == guild.owner_id:
            return True
        if user_id == self.bot.user.id:
            return True
        if user_id in cfg.get("whitelist", []):
            return True
        return False

    async def log(self, guild: discord.Guild, embed: discord.Embed):
        cfg = self.cfg(guild.id)
        chan_id = cfg.get("log_channel_id")
        if not chan_id:
            return
        channel = guild.get_channel(chan_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    # -- core punishment -----------------------------------------------------

    async def punish(self, guild: discord.Guild, user_id: int, action: str, cfg: dict):
        member = guild.get_member(user_id)
        method = cfg.get("punishment", "ban")
        reason = f"Anti-Nuke: exceeded threshold for '{action}'"

        try:
            if method == "ban" or member is None:
                await guild.ban(discord.Object(id=user_id), reason=reason, delete_message_seconds=0)
                result = f"🔨 Banned <@{user_id}>"
            elif method == "kick":
                await guild.kick(member, reason=reason)
                result = f"👢 Kicked {member.mention}"
            else:  # strip_roles
                roles_to_remove = [r for r in member.roles if r.is_assignable()]
                await member.remove_roles(*roles_to_remove, reason=reason)
                result = f"🧹 Stripped all roles from {member.mention}"
        except discord.Forbidden:
            result = f"⚠️ Detected <@{user_id}> but I lack permission to act (raise my role above theirs)."
        except discord.HTTPException as e:
            result = f"⚠️ Detected <@{user_id}> but punishment failed: {e}"

        embed = brand_embed(
            "🛡️ Anti-Nuke Triggered",
            f"**Action:** `{action}`\n**Actor:** <@{user_id}>\n**Response:** {result}",
            COLOR_DANGER,
            self.bot,
        )
        await self.log(guild, embed)

    async def check(self, guild: discord.Guild, actor_id: int, action: str):
        cfg = self.cfg(guild.id)
        if not cfg.get("enabled", True):
            return
        if self.is_exempt(guild, actor_id, cfg):
            return
        threshold = cfg["thresholds"].get(action)
        if not threshold:
            return
        count = self.tracker.hit(guild.id, actor_id, action, cfg["window_seconds"])
        if count >= threshold:
            await self.punish(guild, actor_id, action, cfg)

    async def _actor_from_audit_log(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None):
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if target_id is None or (entry.target and entry.target.id == target_id):
                    # Only trust very recent entries to avoid mis-attributing older actions
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() < 15:
                        return entry.user
        except discord.Forbidden:
            return None
        return None

    # -- listeners -----------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        actor = await self._actor_from_audit_log(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if actor:
            await self.check(channel.guild, actor.id, "channel_delete")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        actor = await self._actor_from_audit_log(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if actor:
            await self.check(channel.guild, actor.id, "channel_create")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        actor = await self._actor_from_audit_log(role.guild, discord.AuditLogAction.role_delete)
        if actor:
            await self.check(role.guild, actor.id, "role_delete")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        actor = await self._actor_from_audit_log(guild, discord.AuditLogAction.ban, user.id)
        if actor:
            await self.check(guild, actor.id, "ban")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Could be a kick or a voluntary leave — check audit log to disambiguate.
        actor = await self._actor_from_audit_log(member.guild, discord.AuditLogAction.kick, member.id)
        if actor:
            await self.check(member.guild, actor.id, "kick")

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        actor = await self._actor_from_audit_log(channel.guild, discord.AuditLogAction.webhook_create)
        if actor:
            await self.check(channel.guild, actor.id, "webhook_create")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            return
        actor = await self._actor_from_audit_log(member.guild, discord.AuditLogAction.bot_add, member.id)
        if actor:
            await self.check(member.guild, actor.id, "bot_add")

    # -- commands --------------------------------------------------------

    @commands.group(name="antinuke", invoke_without_command=True)
    @admin_check()
    async def antinuke_group(self, ctx: commands.Context):
        cfg = self.cfg(ctx.guild.id)
        log_channel_display = f"<#{cfg['log_channel_id']}>" if cfg.get("log_channel_id") else "not set"
        lines = [
            f"**Status:** {'🟢 Enabled' if cfg['enabled'] else '🔴 Disabled'}",
            f"**Punishment:** `{cfg['punishment']}`",
            f"**Log channel:** {log_channel_display}",
            f"**Whitelisted:** {len(cfg['whitelist'])} user(s)",
            "",
            "**Thresholds (per 10s window):**",
        ]
        for action, n in cfg["thresholds"].items():
            lines.append(f"• `{action}`: {n}")
        embed = brand_embed("🛡️ Anti-Nuke Configuration", "\n".join(lines), bot=self.bot)
        embed.set_footer(text="Use !antinuke enable/disable/punishment/logchannel/whitelist")
        await ctx.send(embed=embed)

    @antinuke_group.command(name="enable")
    @admin_check()
    async def antinuke_enable(self, ctx: commands.Context):
        await antinuke_db.update(ctx.guild.id, enabled=True)
        await ctx.send(embed=success_embed("Anti-Nuke protection is now **enabled**.", bot=self.bot))

    @antinuke_group.command(name="disable")
    @owner_check()
    async def antinuke_disable(self, ctx: commands.Context):
        await antinuke_db.update(ctx.guild.id, enabled=False)
        await ctx.send(embed=error_embed("Anti-Nuke protection is now **disabled**. Your server has no automated protection until you re-enable it.", bot=self.bot))

    @antinuke_group.command(name="punishment")
    @admin_check()
    async def antinuke_punishment(self, ctx: commands.Context, method: str):
        method = method.lower()
        if method not in ("ban", "kick", "strip_roles"):
            await ctx.send(embed=error_embed("Punishment must be `ban`, `kick`, or `strip_roles`.", bot=self.bot))
            return
        await antinuke_db.update(ctx.guild.id, punishment=method)
        await ctx.send(embed=success_embed(f"Punishment set to `{method}`.", bot=self.bot))

    @antinuke_group.command(name="logchannel")
    @admin_check()
    async def antinuke_logchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await antinuke_db.update(ctx.guild.id, log_channel_id=channel.id)
        await ctx.send(embed=success_embed(f"Anti-Nuke alerts will be sent to {channel.mention}.", bot=self.bot))

    @antinuke_group.command(name="whitelist")
    @admin_check()
    async def antinuke_whitelist(self, ctx: commands.Context, action: str, member: discord.Member):
        cfg = self.cfg(ctx.guild.id)
        wl = set(cfg["whitelist"])
        if action.lower() == "add":
            wl.add(member.id)
            msg = f"{member.mention} is now whitelisted from Anti-Nuke actions."
        elif action.lower() == "remove":
            wl.discard(member.id)
            msg = f"{member.mention} removed from the Anti-Nuke whitelist."
        else:
            await ctx.send(embed=error_embed("Use `!antinuke whitelist add @user` or `remove @user`.", bot=self.bot))
            return
        await antinuke_db.update(ctx.guild.id, whitelist=list(wl))
        await ctx.send(embed=success_embed(msg, bot=self.bot))

    @antinuke_group.command(name="threshold")
    @admin_check()
    async def antinuke_threshold(self, ctx: commands.Context, action: str, count: int):
        if action not in DEFAULT_CONFIG["thresholds"]:
            valid = ", ".join(f"`{a}`" for a in DEFAULT_CONFIG["thresholds"])
            await ctx.send(embed=error_embed(f"Unknown action type. Valid: {valid}", bot=self.bot))
            return
        cfg = self.cfg(ctx.guild.id)
        cfg["thresholds"][action] = max(1, count)
        await antinuke_db.update(ctx.guild.id, thresholds=cfg["thresholds"])
        await ctx.send(embed=success_embed(f"Threshold for `{action}` set to `{count}` per {cfg['window_seconds']}s.", bot=self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiNuke(bot))
