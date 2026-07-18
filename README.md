# All-in-One Discord Bot — AI Chat, Moderation, Anti-Nuke & Music

A single 24/7 Discord bot that bundles:
- 🤖 **AI chat** (Claude API) — mention it, reply to it, or talk in a configured AI channel
- 🧹 **Continuous moderation** — automod for spam, invites, mass mentions, banned words, caps, plus warn/kick/ban/timeout/purge commands with a mod-log
- 🛡️ **Anti-Nuke protection** — detects and auto-punishes mass channel/role deletion, mass bans/kicks, webhook spam, and surprise bot adds
- 🎶 **Music** — plays from YouTube (and anything `yt-dlp` supports) with a queue, skip/pause/volume, and a "Now Playing" embed
- 🎛️ **Branded, interactive UI** — dropdown help menu, confirm buttons before destructive actions, embed pagination

Runs as its own **bot profile** — separate name, avatar, and identity from your personal account.

## 1. Create the bot's Discord profile
1. Go to https://discord.com/developers/applications → **New Application**
2. Give it a name (bot's display name) and avatar
3. Left sidebar → **Bot** → **Reset Token** → copy it (this is `DISCORD_TOKEN`)
4. On the same Bot page, enable **all three Privileged Gateway Intents**:
   `Presence Intent`, `Server Members Intent`, `Message Content Intent`
5. Left sidebar → **OAuth2 → URL Generator** → check `bot` scope, then under
   **Bot Permissions** check:
   - View Channels, Send Messages, Embed Links, Read Message History, Manage Messages
   - Kick Members, Ban Members, Moderate Members (for timeouts)
   - Manage Roles (for `strip_roles` anti-nuke punishment — keep the bot's role near the top)
   - View Audit Log (**required** — anti-nuke reads it to identify who did what)
   - Connect, Speak (for music)
6. Copy the generated URL, open it, add the bot to your server
7. **Move the bot's role near the top of your role list** (Server Settings → Roles).
   This isn't optional — Discord won't let a bot moderate/punish anyone whose
   role sits above its own, which defeats the anti-nuke and moderation features.

## 2. Get an Anthropic API key
https://console.anthropic.com/settings/keys → create a key (`ANTHROPIC_API_KEY`)

## 3. Install FFmpeg (for music)
- **Railway**: add a `nixpacks.toml` with `[phases.setup] nixPkgs = ["ffmpeg"]`, or use a Docker deploy that installs `ffmpeg`.
- **Local/VPS**: `apt install ffmpeg` (Debian/Ubuntu) or the equivalent for your OS.

## 4. Configure environment variables
Copy `.env.example` → `.env` for local testing, or set the same keys in your
host's **Variables** panel. At minimum set `DISCORD_TOKEN`, `ANTHROPIC_API_KEY`,
and `BOT_OWNER_IDS` (your own Discord user ID — enable Developer Mode, right-click
yourself, Copy User ID). Owner IDs bypass every permission check, so keep that list short.

## 5. Push to GitHub, then deploy
1. Create a repo, upload everything **except** a real `.env` (already gitignored)
2. https://railway.app → New Project → **Deploy from GitHub repo**
3. Service → **Variables** → add your env vars from step 4
4. Railway auto-detects the `Procfile` and runs `python bot.py`
5. Check **Logs** for `Logged in as YourBot#1234`

## Local testing
```bash
pip install -r requirements.txt
cp .env.example .env   # fill in real keys
python bot.py
```

## First-run setup in your server
Once the bot is online, an admin should run:
```
!automod logchannel #mod-log
!antinuke logchannel #mod-log
!antinuke enable
!automod toggle on
```
Everything works with sane defaults out of the box, but setting a log channel
means you'll actually see what the bot catches and punishes.

## Security model — read this before adopting the bot into a new server
- **Role hierarchy is the real security boundary.** The bot can never act on
  a member whose highest role sits above its own — that's a Discord platform
  rule, not a bug. Keep the bot's role high, and keep roles you don't fully
  trust below it.
- **Bot owner (`BOT_OWNER_IDS`) bypasses everything**, in every server the
  bot is in. Only put your own account(s) there.
- **Anti-Nuke whitelist** (`!antinuke whitelist add @user`) exempts a member
  from anti-nuke punishment in that one server — use it for trusted admins
  who legitimately do bulk changes (e.g. during a planned channel restructure).
- **Destructive commands (`!ban`) ask for confirmation** via a button before
  running, so a mis-typed command can't immediately ban someone.
- Nothing here can stop a compromised **server owner** account or someone
  with **Administrator** who out-permissions the bot — no bot can override
  Discord's own permission system. Anti-nuke reduces blast radius; it isn't a substitute for careful role/permission hygiene.

## Command reference
Run `!help` in Discord for the interactive menu, or see below.

**Moderation:** `!warn` `!warnings` `!clearwarnings` `!kick` `!ban` `!unban` `!timeout` `!untimeout` `!purge` `!automod`
**Anti-Nuke:** `!antinuke` `!antinuke enable/disable` `!antinuke punishment` `!antinuke logchannel` `!antinuke whitelist` `!antinuke threshold`
**Music:** `!play` `!skip` `!pause` `!resume` `!stop` `!queue` `!nowplaying` `!volume` `!join`
**AI Chat:** `@mention` or reply to chat, `!ask`, `!reset`
**Utility:** `!ping` `!uptime` `!channelid` `!serverinfo` `!userinfo` `!botinfo` `!help`

## Project structure
```
discord-ai-bot/
├── bot.py                  # entry point, cog loader, global error handler
├── keep_alive.py           # tiny Flask server for uptime pings
├── cogs/
│   ├── ai_chat.py           # AI auto-reply logic
│   ├── admin.py             # ping/uptime/serverinfo/userinfo
│   ├── moderation.py        # automod + warn/kick/ban/timeout/purge
│   ├── antinuke.py          # mass-action detection & auto-punishment
│   ├── music.py             # voice playback, queue, controls
│   └── help_menu.py         # branded dropdown help menu
├── utils/
│   ├── storage.py           # JSON per-guild config storage
│   ├── permissions.py       # mod/admin/owner checks, role-hierarchy safety
│   └── ui.py                # branded embeds, buttons, paginator, progress bars
├── requirements.txt
├── .env.example
├── .gitignore
└── Procfile
```

## Notes
- This is a **bot account**, not your personal account — fully compliant with
  Discord's Terms of Service. Automating a personal user account ("self-bot")
  is against Discord's ToS and isn't something this project does.
- Swap `call_ai()` in `cogs/ai_chat.py` if you'd rather use OpenAI or another provider.
- `data/` (JSON config/warnings/antinuke state) is gitignored — make sure your
  host has a persistent volume for it, or configs reset on every redeploy.
