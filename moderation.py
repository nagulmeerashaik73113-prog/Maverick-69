"""
Continuous moderation: automod (spam, invite links, mass mentions, banned
words, link/caps spam) that runs on every message, plus manual mod commands
(warn, kick, ban, timeout, purge) with warning history and a mod-log channel.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord.ext import commands

from utils.storage import guild_config, warnings_db
from utils.ui import brand_embed, success_embed, error_embed, warning_embed, ConfirmView, COLOR_WARNING
from utils.permissions import mod_check, admin_check, can_target

INVITE_RE = re.compile(r"(discord\.gg|discord(app)?\.com/invite)/\S+", re.IGNORECASE)
DEFAULT_AUTOMOD = {
    "enabled": True,
    "banned_words": [],
    "block_invites": True,
    "max_mentions": 6,
    "spam_messages": 5,     # N messages
    "spam_seconds": 5,      # within N seconds -> flagged as spam
    "max_caps_ratio": 0.8,  # ignored for messages shorter than 10 chars
    "log_channel_id": None,
    "mod_role_ids": [],
    "admin_role_ids": [],
}


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {(guild_id, user_id): deque[timestamps]}
        self._recent_msgs: dict[tuple[int, int], deque] = defaultdict(deque)

    def cfg(self, guild_id: int) -> dict:
        stored = guild_config.get(guild_id, {})
        return {**DEFAULT_AUTOMOD, **stored}

    async def modlog(self, guild: discord.Guild, embed: discord.Embed):
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

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str):
        data = warnings_db.get(guild_id, {})
        user_warns = data.setdefault(str(user_id), [])
        user_warns.append({"reason": reason, "moderator": moderator_id, "ts": time.time()})
        await warnings_db.set(guild_id, data)
        return len(user_warns)

    # -- automod ---------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        cfg = self.cfg(message.guild.id)
        if not cfg.get("enabled", True):
            return
        member = message.author
        if isinstance(member, discord.Member) and (member.guild_permissions.administrator):
            return  # never automod admins

        violation = None

        # Banned words
        content_lower = message.content.lower()
        for word in cfg.get("banned_words", []):
            if word and word.lower() in content_lower:
                violation = f"used a banned word (`{word}`)"
                break

        # Invite links
        if not violation and cfg.get("block_invites") and INVITE_RE.search(message.content):
            violation = "posted a Discord invite link"

        # Mass mentions
        if not violation and len(message.mentions) + len(message.role_mentions) > cfg.get("max_mentions", 6):
            violation = "mass-mentioned users/roles"

        # Excess caps (only for longer messages)
        if not violation:
            letters = [c for c in message.content if c.isalpha()]
            if len(letters) >= 10:
                caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
                if caps_ratio > cfg.get("max_caps_ratio", 0.8):
                    violation = "excessive caps"

        # Spam (message frequency)
        if not violation:
            key = (message.guild.id, member.id)
            now = time.time()
            dq = self._recent_msgs[key]
            dq.append(now)
            window = cfg.get("spam_seconds", 5)
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) > cfg.get("spam_messages", 5):
                violation = "sending messages too quickly (spam)"

        if violation:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            try:
                await message.channel.send(
                    embed=warning_embed(f"{member.mention}, that message was removed: **{violation}**.", bot=self.bot),
                    delete_after=6,
                )
            except discord.HTTPException:
                pass
            await self.modlog(
                message.guild,
                brand_embed(
                    "🧹 Automod Action",
                    f"**User:** {member.mention} (`{member.id}`)\n**Channel:** {message.channel.mention}\n**Reason:** {violation}",
                    COLOR_WARNING,
                    self.bot,
                ),
            )

    # -- configuration commands -------------------------------------------

    @commands.group(name="automod", invoke_without_command=True)
    @admin_check()
    async def automod_group(self, ctx: commands.Context):
        cfg = self.cfg(ctx.guild.id)
        log_display = f"<#{cfg['log_channel_id']}>" if cfg.get("log_channel_id") else "not set"
        desc = (
            f"**Status:** {'🟢 Enabled' if cfg['enabled'] else '🔴 Disabled'}\n"
            f"**Block invites:** {cfg['block_invites']}\n"
            f"**Max mentions:** {cfg['max_mentions']}\n"
            f"**Spam limit:** {cfg['spam_messages']} msgs / {cfg['spam_seconds']}s\n"
            f"**Banned words:** {len(cfg['banned_words'])}\n"
            f"**Log channel:** {log_display}"
        )
        await ctx.send(embed=brand_embed("🧹 Automod Configuration", desc, bot=self.bot))

    @automod_group.command(name="toggle")
    @admin_check()
    async def automod_toggle(self, ctx: commands.Context, state: str):
        enabled = state.lower() in ("on", "enable", "true")
        await guild_config.update(ctx.guild.id, enabled=enabled)
        await ctx.send(embed=success_embed(f"Automod is now **{'enabled' if enabled else 'disabled'}**.", bot=self.bot))

    @automod_group.command(name="logchannel")
    @admin_check()
    async def automod_logchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await guild_config.update(ctx.guild.id, log_channel_id=channel.id)
        await ctx.send(embed=success_embed(f"Mod-log channel set to {channel.mention}.", bot=self.bot))

    @automod_group.command(name="bannedword")
    @admin_check()
    async def automod_bannedword(self, ctx: commands.Context, action: str, *, word: str):
        cfg = self.cfg(ctx.guild.id)
        words = set(cfg["banned_words"])
        if action.lower() == "add":
            words.add(word)
            msg = f"Added `{word}` to the banned words list."
        elif action.lower() == "remove":
            words.discard(word)
            msg = f"Removed `{word}` from the banned words list."
        else:
            await ctx.send(embed=error_embed("Use `!automod bannedword add <word>` or `remove <word>`.", bot=self.bot))
            return
        await guild_config.update(ctx.guild.id, banned_words=list(words))
        await ctx.send(embed=success_embed(msg, bot=self.bot))

    @automod_group.command(name="modrole")
    @admin_check()
    async def automod_modrole(self, ctx: commands.Context, action: str, role: discord.Role):
        cfg = self.cfg(ctx.guild.id)
        ids = set(cfg["mod_role_ids"])
        if action.lower() == "add":
            ids.add(role.id)
            msg = f"{role.mention} can now use moderator commands."
        else:
            ids.discard(role.id)
            msg = f"{role.mention} removed from moderator roles."
        await guild_config.update(ctx.guild.id, mod_role_ids=list(ids))
        await ctx.send(embed=success_embed(msg, bot=self.bot))

    # -- manual moderation commands ----------------------------------------

    @commands.command(name="warn")
    @mod_check()
    async def warn_cmd(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        ok, why = can_target(ctx.author, member)
        if not ok:
            await ctx.send(embed=error_embed(why, bot=self.bot))
            return
        count = await self.add_warning(ctx.guild.id, member.id, ctx.author.id, reason)
        await ctx.send(embed=success_embed(f"{member.mention} warned. (Total warnings: **{count}**)\nReason: {reason}", bot=self.bot))
        await self.modlog(ctx.guild, brand_embed("⚠️ Member Warned", f"**User:** {member.mention}\n**Mod:** {ctx.author.mention}\n**Reason:** {reason}", COLOR_WARNING, self.bot))

    @commands.command(name="warnings")
    @mod_check()
    async def warnings_cmd(self, ctx: commands.Context, member: discord.Member):
        data = warnings_db.get(ctx.guild.id, {}).get(str(member.id), [])
        if not data:
            await ctx.send(embed=brand_embed("Warnings", f"{member.mention} has no warnings.", bot=self.bot))
            return
        lines = [f"**{i+1}.** {w['reason']} — <t:{int(w['ts'])}:R>" for i, w in enumerate(data)]
        await ctx.send(embed=brand_embed(f"Warnings for {member}", "\n".join(lines), bot=self.bot))

    @commands.command(name="clearwarnings")
    @admin_check()
    async def clearwarnings_cmd(self, ctx: commands.Context, member: discord.Member):
        data = warnings_db.get(ctx.guild.id, {})
        data[str(member.id)] = []
        await warnings_db.set(ctx.guild.id, data)
        await ctx.send(embed=success_embed(f"Cleared warnings for {member.mention}.", bot=self.bot))

    @commands.command(name="kick")
    @mod_check()
    async def kick_cmd(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        ok, why = can_target(ctx.author, member)
        if not ok:
            await ctx.send(embed=error_embed(why, bot=self.bot))
            return
        try:
            await member.kick(reason=f"{reason} (by {ctx.author})")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to kick that member.", bot=self.bot))
            return
        await ctx.send(embed=success_embed(f"👢 {member.mention} was kicked.\nReason: {reason}", bot=self.bot))
        await self.modlog(ctx.guild, brand_embed("👢 Member Kicked", f"**User:** {member} (`{member.id}`)\n**Mod:** {ctx.author.mention}\n**Reason:** {reason}", bot=self.bot))

    @commands.command(name="ban")
    @mod_check()
    async def ban_cmd(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        ok, why = can_target(ctx.author, member)
        if not ok:
            await ctx.send(embed=error_embed(why, bot=self.bot))
            return
        view = ConfirmView(ctx.author.id)
        confirm_msg = await ctx.send(
            embed=warning_embed(f"Ban {member.mention}? This can't be undone from Discord's side without re-inviting them.", bot=self.bot),
            view=view,
        )
        await view.wait()
        if not view.value:
            await confirm_msg.edit(embed=error_embed("Ban cancelled.", bot=self.bot), view=None)
            return
        try:
            await member.ban(reason=f"{reason} (by {ctx.author})", delete_message_seconds=0)
        except discord.Forbidden:
            await confirm_msg.edit(embed=error_embed("I don't have permission to ban that member.", bot=self.bot), view=None)
            return
        await confirm_msg.edit(embed=success_embed(f"🔨 {member.mention} was banned.\nReason: {reason}", bot=self.bot), view=None)
        await self.modlog(ctx.guild, brand_embed("🔨 Member Banned", f"**User:** {member} (`{member.id}`)\n**Mod:** {ctx.author.mention}\n**Reason:** {reason}", bot=self.bot))

    @commands.command(name="timeout")
    @mod_check()
    async def timeout_cmd(self, ctx: commands.Context, member: discord.Member, minutes: int, *, reason: str = "No reason provided"):
        ok, why = can_target(ctx.author, member)
        if not ok:
            await ctx.send(embed=error_embed(why, bot=self.bot))
            return
        minutes = max(1, min(minutes, 40320))  # Discord's cap is 28 days
        try:
            await member.timeout(timedelta(minutes=minutes), reason=f"{reason} (by {ctx.author})")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to time out that member.", bot=self.bot))
            return
        await ctx.send(embed=success_embed(f"🔇 {member.mention} timed out for **{minutes} min**.\nReason: {reason}", bot=self.bot))
        await self.modlog(ctx.guild, brand_embed("🔇 Member Timed Out", f"**User:** {member} (`{member.id}`)\n**Duration:** {minutes} min\n**Mod:** {ctx.author.mention}\n**Reason:** {reason}", bot=self.bot))

    @commands.command(name="untimeout")
    @mod_check()
    async def untimeout_cmd(self, ctx: commands.Context, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to do that.", bot=self.bot))
            return
        await ctx.send(embed=success_embed(f"{member.mention}'s timeout was removed.", bot=self.bot))

    @commands.command(name="purge", aliases=["clear"])
    @mod_check()
    async def purge_cmd(self, ctx: commands.Context, amount: int):
        amount = max(1, min(amount, 500))
        try:
            await ctx.channel.purge(limit=amount + 1)  # +1 to include the command message
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to delete messages here.", bot=self.bot))
            return
        confirm = await ctx.send(embed=success_embed(f"🧹 Deleted **{amount}** messages.", bot=self.bot))
        await confirm.delete(delay=4)

    @commands.command(name="unban")
    @mod_check()
    async def unban_cmd(self, ctx: commands.Context, user_id: int, *, reason: str = "No reason provided"):
        try:
            await ctx.guild.unban(discord.Object(id=user_id), reason=f"{reason} (by {ctx.author})")
        except discord.NotFound:
            await ctx.send(embed=error_embed("That user isn't banned.", bot=self.bot))
            return
        except discord.Forbidden:
            await ctx.send(embed=error_embed("I don't have permission to unban.", bot=self.bot))
            return
        await ctx.send(embed=success_embed(f"Unbanned `<@{user_id}>`.", bot=self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
