"""
Custom branded help command: a dropdown-driven category menu instead of the
default plain-text help list. Replaces discord.py's default help command
(bot.py sets help_command=None and loads this cog instead).
"""

from __future__ import annotations

import discord
from discord.ext import commands

from utils.ui import brand_embed, COLOR_PRIMARY

CATEGORIES = {
    "🛡️ Moderation": (
        "!warn @user <reason>\n!warnings @user\n!kick @user <reason>\n!ban @user <reason>\n"
        "!timeout @user <minutes>\n!untimeout @user\n!purge <amount>\n!unban <user_id>\n"
        "!automod  •  !automod toggle on/off  •  !automod bannedword add/remove\n!automod logchannel #channel"
    ),
    "⚔️ Anti-Nuke": (
        "!antinuke — view config\n!antinuke enable / disable\n!antinuke punishment ban|kick|strip_roles\n"
        "!antinuke logchannel #channel\n!antinuke whitelist add/remove @user\n!antinuke threshold <action> <count>"
    ),
    "🎶 Music": (
        "!play <song/url>  •  !skip  •  !pause  •  !resume\n!queue  •  !nowplaying  •  !volume <0-150>\n!stop"
    ),
    "🤖 AI Chat": (
        "@mention me or reply to my message to chat\n!ask <question>\n!reset — clear this channel's AI memory"
    ),
    "🔧 Utility": (
        "!ping  •  !uptime  •  !channelid\n!serverinfo  •  !userinfo @user  •  !botinfo"
    ),
}


class CategorySelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        options = [
            discord.SelectOption(label=name.split(" ", 1)[1], emoji=name.split(" ", 1)[0], value=name)
            for name in CATEGORIES
        ]
        super().__init__(placeholder="Choose a category...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        embed = discord.Embed(title=name, description=CATEGORIES[name], color=COLOR_PRIMARY)
        if self.bot.user:
            embed.set_footer(text=f"{self.bot.user.name} • prefix: !")
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.add_item(CategorySelect(bot))


class HelpMenu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_cmd(self, ctx: commands.Context, *, command_name: str = None):
        if command_name:
            cmd = self.bot.get_command(command_name)
            if not cmd:
                await ctx.send(embed=brand_embed("❌ Not found", f"No command called `{command_name}`.", bot=self.bot))
                return
            embed = brand_embed(f"!{cmd.name}", cmd.help or "No description.", bot=self.bot)
            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join(cmd.aliases))
            await ctx.send(embed=embed)
            return

        embed = brand_embed(
            "📖 Command Menu",
            "Pick a category from the dropdown below to see its commands.\n\n"
            "This bot bundles **AI chat**, **continuous moderation**, **anti-nuke protection**, "
            "and **music** into one always-on assistant for your server.",
            bot=self.bot,
        )
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        await ctx.send(embed=embed, view=HelpView(self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpMenu(bot))
