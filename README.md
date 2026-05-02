# Securit System Discord Bot

Securit System is a Discord moderation bot focused on automatic server protection against profanity, invite links, spam, raid joins, nuke-style abuse, and image spam.

## Features

- **AutoMod toggle per server** (enabled by default).
- **Prohibited language filtering** with simple obfuscation normalization.
- **Discord invite link blocking**.
- **Text spam detection** using rolling message windows.
- **Raid join detection** using rolling member-join windows.
- **Anti-nuke detection** for suspicious moderation/channel activity bursts.
- **Image spam detection** across channels in a short time window.
- Built with `discord.py` and configured through environment variables.

## Requirements

- Python 3.10+
- A Discord bot token

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root with:

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

## Run locally

```bash
python bot.py
```

## Deploy with Procfile

This repository includes a `Procfile` for worker-style deployment:

```bash
worker: python bot.py
```

## Notes

- Message content intent must be enabled in the Discord Developer Portal.
- Moderation state is stored in-memory and resets on bot restart.
