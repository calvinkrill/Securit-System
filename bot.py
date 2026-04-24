import os
import re

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Initialize bot intents
# Message content intent must be enabled in the Discord Developer Portal.
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Per-guild automod toggle (defaults to enabled)
automod_enabled_by_guild: dict[int, bool] = {}

# Word lists for auto moderation
BAD_WORDS = {
    "curse": {
        "damn",
        "shit",
        "bitch",
        "asshole",
        "bastard",
        "fuck",
        "fucker",
        "fucking",
    },
    "sexual": {
        "sex",
        "sexy",
        "porn",
        "nude",
        "blowjob",
        "dogstyle",
        "doggystyle",
        "threesome",
        "handjob",
    },
    "harassment": {
        "idiot",
        "moron",
        "loser",
        "stupid",
        "retard",
        "kys",
        "kill yourself",
    },
    "racist": {
        "nigger",
        "nigga",
        "chink",
        "spic",
        "gook",
        "wetback",
    },
}

# Flatten all terms to one set and escape for regex matching
ALL_FLAGGED_TERMS = set().union(*BAD_WORDS.values())
ESCAPED_TERMS = sorted((re.escape(term) for term in ALL_FLAGGED_TERMS), key=len, reverse=True)
FLAGGED_PATTERN = re.compile(rf"\\b({'|'.join(ESCAPED_TERMS)})\\b", re.IGNORECASE)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} slash command(s)")
    print("------")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    guild_id = message.guild.id if message.guild else None
    automod_enabled = True if guild_id is None else automod_enabled_by_guild.get(guild_id, True)

    if automod_enabled:
        found = FLAGGED_PATTERN.search(message.content)
        if found:
            try:
                await message.delete()
                warning = (
                    f"⚠️ {message.author.mention}, your message was removed because it contains "
                    "prohibited language (curse, sexual, harassment, or racist terms)."
                )
                await message.channel.send(warning, delete_after=10)
            except discord.Forbidden:
                await message.channel.send(
                    "⚠️ I detected prohibited words but I don't have permission to delete messages.",
                    delete_after=10,
                )
            except discord.HTTPException:
                pass
            return

    await bot.process_commands(message)


@bot.command()
async def ping(ctx: commands.Context):
    """Responds with Pong!"""
    await ctx.send("Pong!")


@bot.command()
async def echo(ctx: commands.Context, *, message: str):
    """Echoes back the message provided."""
    await ctx.send(message)


@bot.tree.command(name="automod", description="Toggle automatic moderation on or off for this server.")
@app_commands.describe(state="Choose whether automod should be on or off")
@app_commands.choices(
    state=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ]
)
@app_commands.default_permissions(manage_messages=True)
async def automod(interaction: discord.Interaction, state: app_commands.Choice[str]):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    enabled = state.value == "on"
    automod_enabled_by_guild[interaction.guild.id] = enabled

    await interaction.response.send_message(
        f"✅ Auto moderation is now **{'ON' if enabled else 'OFF'}** for this server.",
        ephemeral=True,
    )


if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
