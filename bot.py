import os
import re
import unicodedata
from collections import defaultdict, deque
from datetime import timedelta

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
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Per-guild automod toggle (defaults to enabled)
automod_enabled_by_guild: dict[int, bool] = {}

# Word lists for auto moderation.
# NOTE: This list intentionally includes terms from multiple categories/languages,
# including common Bisaya profanity samples requested by the user.
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
        "bullshit",
        "motherfucker",
        "piste",
        "yawa",
        "animal",
        "buang",
        "giatay",
        "atay",
        "leche",
        "ulol",
        "putangina",
        "puta",
        "gago",
        "tanga",
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
        "nudes",
        "anal",
        "oral sex",
        "gangbang",
        "cum",
        "horny",
    },
    "harassment": {
        "idiot",
        "moron",
        "loser",
        "stupid",
        "retard",
        "kys",
        "kill yourself",
        "die",
        "go die",
        "ugly",
        "fatso",
        "slut",
        "whore",
    },
    "racist_or_hate": {
        "nigger",
        "nigga",
        "chink",
        "spic",
        "gook",
        "wetback",
        "faggot",
        "tranny",
    },
}

LEETSPEAK_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
        "!": "i",
    }
)


# Flatten all terms to one set and escape for regex matching.
# Use look-around boundaries so multi-word terms also match reliably.
ALL_FLAGGED_TERMS = set().union(*BAD_WORDS.values())
ESCAPED_TERMS = sorted((re.escape(term) for term in ALL_FLAGGED_TERMS), key=len, reverse=True)
FLAGGED_PATTERN = re.compile(rf"(?<!\\w)({'|'.join(ESCAPED_TERMS)})(?!\\w)", re.IGNORECASE)
DISCORD_INVITE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+",
    re.IGNORECASE,
)

# Anti-spam / anti-raid / anti-nuke configuration
SPAM_WINDOW_SECONDS = 8
SPAM_MESSAGE_THRESHOLD = 6
RAID_WINDOW_SECONDS = 12
RAID_JOIN_THRESHOLD = 6
NUKE_WINDOW_SECONDS = 18
NUKE_ACTION_THRESHOLD = 3
NUKE_BAN_REASON = "Automatic anti-nuke protection triggered."
SPAM_BAN_REASON = "Automatic anti-spam protection triggered."
RAID_BAN_REASON = "Automatic anti-raid protection triggered."

# In-memory trackers (reset on bot restart)
member_message_timestamps: dict[int, deque[float]] = defaultdict(deque)
guild_join_timestamps: dict[int, deque[float]] = defaultdict(deque)
guild_nuke_action_timestamps: dict[int, dict[int, deque[float]]] = defaultdict(
    lambda: defaultdict(deque)
)


def prune_timestamps(queue: deque[float], now_ts: float, window_seconds: int) -> None:
    """Keep only timestamps inside a rolling window."""
    cutoff = now_ts - window_seconds
    while queue and queue[0] < cutoff:
        queue.popleft()



def normalize_for_moderation(content: str) -> str:
    """Normalize message text to catch common obfuscation tactics."""
    text = unicodedata.normalize("NFKD", content)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(LEETSPEAK_MAP)
    # Remove punctuation/underscores separators to catch f.u.c.k or f_u_c_k
    text = re.sub(r"[\W_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
        # Anti-spam: timeout users who send too many messages quickly.
        if message.guild and isinstance(message.author, discord.Member):
            now_ts = discord.utils.utcnow().timestamp()
            key = (message.guild.id << 22) + message.author.id
            spam_queue = member_message_timestamps[key]
            spam_queue.append(now_ts)
            prune_timestamps(spam_queue, now_ts, SPAM_WINDOW_SECONDS)

            if len(spam_queue) >= SPAM_MESSAGE_THRESHOLD:
                try:
                    await message.guild.ban(
                        message.author,
                        reason=SPAM_BAN_REASON,
                        delete_message_days=0,
                    )
                    await message.channel.send(
                        f"🛑 {message.author.mention} has been permanently banned for spam "
                        f"({SPAM_MESSAGE_THRESHOLD}+ messages in {SPAM_WINDOW_SECONDS}s).",
                        delete_after=12,
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                finally:
                    spam_queue.clear()
                return

        invite_found = DISCORD_INVITE_PATTERN.search(message.content)
        if invite_found and message.guild and isinstance(message.author, discord.Member):
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

            try:
                await message.author.timeout(
                    discord.utils.utcnow() + timedelta(days=14),
                    reason="Posted a Discord server invite link.",
                )
                await message.channel.send(
                    f"⛔ {message.author.mention} has been timed out for 2 weeks for posting a Discord invite link.",
                    delete_after=12,
                )
            except discord.Forbidden:
                await message.channel.send(
                    "⚠️ I detected a Discord invite link but I don't have permission to timeout this user.",
                    delete_after=10,
                )
            except discord.HTTPException:
                pass
            return

        content_to_check = normalize_for_moderation(message.content)
        found = FLAGGED_PATTERN.search(content_to_check)
        if found:
            matched_term = found.group(1)
            try:
                await message.delete()
                warning = (
                    f"⚠️ {message.author.mention}, your message was removed automatically because it "
                    f"contains prohibited language (detected: `{matched_term}`). "
                    "Please avoid curse, sexual, harassment, and hate/racist words."
                )
                await message.channel.send(warning, delete_after=12)
            except discord.Forbidden:
                await message.channel.send(
                    "⚠️ I detected prohibited words but I don't have permission to delete messages.",
                    delete_after=10,
                )
            except discord.HTTPException:
                pass
            return

    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    automod_enabled = automod_enabled_by_guild.get(guild.id, True)
    if not automod_enabled:
        return

    now_ts = discord.utils.utcnow().timestamp()
    join_queue = guild_join_timestamps[guild.id]
    join_queue.append(now_ts)
    prune_timestamps(join_queue, now_ts, RAID_WINDOW_SECONDS)

    # Anti-raid: if many users join quickly, instantly ban newly joining users.
    if len(join_queue) >= RAID_JOIN_THRESHOLD:
        try:
            await guild.ban(
                member,
                reason=RAID_BAN_REASON,
                delete_message_days=0,
            )
            if guild.system_channel:
                await guild.system_channel.send(
                    f"🚨 Anti-raid active: {member.mention} was permanently banned."
                )
        except (discord.Forbidden, discord.HTTPException):
            pass


async def handle_potential_nuke(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target,
) -> None:
    automod_enabled = automod_enabled_by_guild.get(guild.id, True)
    if not automod_enabled:
        return

    try:
        entry = await anext(guild.audit_logs(limit=1, action=action))
    except (StopAsyncIteration, discord.Forbidden, discord.HTTPException):
        return

    if entry.target.id != target.id or entry.user is None or entry.user.bot:
        return

    now_ts = discord.utils.utcnow().timestamp()
    actor_id = entry.user.id
    action_queue = guild_nuke_action_timestamps[guild.id][actor_id]
    action_queue.append(now_ts)
    prune_timestamps(action_queue, now_ts, NUKE_WINDOW_SECONDS)

    if len(action_queue) >= NUKE_ACTION_THRESHOLD:
        try:
            await guild.ban(entry.user, reason=NUKE_BAN_REASON, delete_message_days=0)
            if guild.system_channel:
                await guild.system_channel.send(
                    f"🛡️ Anti-nuke: Banned {entry.user.mention} for repeated destructive actions."
                )
        except (discord.Forbidden, discord.HTTPException):
            pass
        finally:
            action_queue.clear()


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    await handle_potential_nuke(channel.guild, discord.AuditLogAction.channel_delete, channel)


@bot.event
async def on_guild_role_delete(role: discord.Role):
    await handle_potential_nuke(role.guild, discord.AuditLogAction.role_delete, role)


@bot.tree.command(name="ping", description="Respond with Pong!")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


@bot.tree.command(name="echo", description="Echo back the message provided.")
@app_commands.describe(message="The message you want the bot to repeat")
async def echo(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)


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


@bot.tree.command(name="commands", description="Show all available custom slash commands.")
async def commands_list(interaction: discord.Interaction):
    custom_commands = [
        ("/ping", "Respond with Pong!"),
        ("/echo <message>", "Echo back the message provided."),
        (
            "/automod <on|off>",
            "Toggle anti-spam, anti-raid, anti-nuke, bad-word filter, and anti-invite on/off.",
        ),
        ("/commands", "Show all available custom slash commands."),
    ]

    lines = [f"• **{name}** — {description}" for name, description in custom_commands]
    await interaction.response.send_message(
        "Here are the custom slash commands:\n" + "\n".join(lines),
        ephemeral=True,
    )


if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
