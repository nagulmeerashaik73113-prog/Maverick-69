"""
Utility/admin commands: ping, uptime, channelid, serverinfo, userinfo.
"""

from __future__ import annotations

import time
import platform

import discord
from discord.ext import commands

from utils.ui import brand_embed
from utils.permissions import admin_check

START_TIME = time.time()


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping_cmd(self, ctx: commands.Context):
        start = time.perf_counter()
        msg = await ctx.send(embed=brand_embed("🏓 Pinging...", bot=self.bot))
        elapsed_ms = (time.perf_counter() - start) * 1000
        embed = brand_embed(
            "🏓 Pong!",
            f"**Message latency:** {elapsed_ms:.0f}ms\n**API latency:** {self.bot.latency * 1000:.0f}ms",
            bot=self.bot,
        )
        await msg.edit(embed=embed)

    @commands.command(name="uptime")
    async def uptime_cmd(self, ctx: commands.Context):
        seconds = int(time.time() - START_TIME)
        d, seconds = divmod(seconds, 86400)
        h, seconds = divmod(seconds, 3600)
        m, s = divmod(seconds, 60)
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        parts.append(f"{s}s")
        await ctx.send(embed=brand_embed("⏱️ Uptime", " ".join(parts), bot=self.bot))

    @commands.command(name="channelid")
    async def channelid_cmd(self, ctx: commands.Context):
        await ctx.send(embed=brand_embed("🆔 Channel ID", f"`{ctx.channel.id}`", bot=self.bot))

    @commands.command(name="serverinfo", aliases=["guildinfo"])
    async def serverinfo_cmd(self, ctx: commands.Context):
        g = ctx.guild
        embed = brand_embed(f"📊 {g.name}", bot=self.bot)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>", inline=True)
        embed.add_field(name="Members", value=str(g.member_count), inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"), inline=True)
        embed.add_field(name="Text channels", value=str(len(g.text_channels)), inline=True)
        embed.add_field(name="Voice channels", value=str(len(g.voice_channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(g.roles)), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="userinfo", aliases=["whois"])
    async def userinfo_cmd(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = brand_embed(f"👤 {member}", bot=self.bot)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Joined server", value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        top_roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"][:10]
        embed.add_field(name="Roles", value=" ".join(top_roles) if top_roles else "None", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="botinfo", aliases=["about"])
    async def botinfo_cmd(self, ctx: commands.Context):
        embed = brand_embed(
            "🤖 About this bot",
            "AI chat, continuous moderation, anti-nuke protection, and music — all in one bot.",
            bot=self.bot,
        )
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
