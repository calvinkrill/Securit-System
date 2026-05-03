# Securit System Discord Bot

Securit System is a Discord moderation bot focused on automatic server protection against profanity, invite links, spam floods, raid joins, nuke-style abuse, and cross-channel image spam.

## What’s New

- Added **cross-channel image spam detection** with automatic bans for high-volume image flooding.
- Added **server-level AutoMod toggle** (`/automod on|off`) with clear ON/OFF announcement messages.
- Expanded **slash command set** with utility and moderation helpers: `/ping`, `/echo`, `/say`, `/automod`, `/commands`.
- Improved **prohibited language detection** with normalization for accents, punctuation splitting, underscores, and common leetspeak substitutions.
- Added **destructive action burst detection** (anti-nuke) based on Discord audit-log events.

## Features

### Core AutoMod protections

- **Prohibited language filter**
  - Detects curse words, sexual terms, harassment language, and hate/racist slurs.
  - Normalizes text before scanning to catch obfuscated terms (e.g., punctuated or leetspeak variants).
  - Action: deletes message and posts an automatic warning.

- **Discord invite link blocking**
  - Detects common `discord.gg` and `discord.com/invite` link formats.
  - Action: deletes message and applies a **14-day timeout**.

- **Text spam/flood protection**
  - Tracks per-user message bursts in a rolling window.
  - Default threshold: **6+ messages in 8 seconds**.
  - Action: **10-minute timeout**.

- **Raid join protection**
  - Tracks rapid member joins per guild.
  - Default threshold: **6+ joins in 12 seconds**.
  - Action: **30-minute timeout** for flagged joiners.

- **Anti-nuke protection**
  - Monitors rapid destructive moderation actions (channel/role deletions) using audit logs.
  - Default threshold: **3+ destructive actions in 18 seconds** by the same actor.
  - Action: automatic **ban**.

- **Image spam protection**
  - Tracks image attachment bursts per user across channels.
  - Default threshold: **8+ image uploads in 25 seconds across 3+ channels**.
  - Action: automatic **ban**.

### Moderation controls and utility commands

- `/automod <on|off>` — Toggle all AutoMod protections per server.
- `/say <message>` — Make the bot post a message in the current channel (requires `Manage Messages`).
- `/commands` — Show available custom slash commands.
- `/ping` — Health check reply.
- `/echo <message>` — Echo helper.

## Requirements

- Python 3.10+
- A Discord bot token

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root:

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

## Discord setup checklist

- Enable **Message Content Intent** in the Discord Developer Portal.
- Ensure the bot has permissions to:
  - Manage Messages
  - Moderate Members (timeouts)
  - Ban Members
  - View Audit Log
  - Send Messages

## Run locally

```bash
python bot.py
```

## Deploy with Procfile

This repository includes a `Procfile` for worker-style deployment:

```bash
worker: python bot.py
```

## Notes and limitations

- Moderation state and counters are currently **in-memory only** and reset when the bot restarts.
- AutoMod is **enabled by default** for guilds unless toggled off via `/automod`.
- Thresholds are currently hardcoded in `bot.py` and can be tuned there.
