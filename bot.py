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
SPAM_TIMEOUT_MINUTES = 10
RAID_WINDOW_SECONDS = 12
RAID_JOIN_THRESHOLD = 6
RAID_TIMEOUT_MINUTES = 30
NUKE_WINDOW_SECONDS = 18
NUKE_ACTION_THRESHOLD = 3
NUKE_BAN_REASON = "Automatic anti-nuke protection triggered."
IMAGE_SPAM_WINDOW_SECONDS = 25
IMAGE_SPAM_ATTACHMENT_THRESHOLD = 8
IMAGE_SPAM_CHANNEL_THRESHOLD = 3
IMAGE_SPAM_BAN_REASON = "Automatic anti-picture spam protection triggered."
CREATE_CHANNEL_MIN = 100
CREATE_CHANNEL_MAX = 250

# In-memory trackers (reset on bot restart)
member_message_timestamps: dict[int, deque[float]] = defaultdict(deque)
guild_join_timestamps: dict[int, deque[float]] = defaultdict(deque)
guild_nuke_action_timestamps: dict[int, dict[int, deque[float]]] = defaultdict(
    lambda: defaultdict(deque)
)
member_image_spam_events: dict[int, deque[tuple[float, int]]] = defaultdict(deque)


def prune_timestamps(queue: deque[float], now_ts: float, window_seconds: int) -> None:
    """Keep only timestamps inside a rolling window."""
    cutoff = now_ts - window_seconds
    while queue and queue[0] < cutoff:
        queue.popleft()



def prune_image_events(
    queue: deque[tuple[float, int]],
    now_ts: float,
    window_seconds: int,
) -> None:
    """Keep only image spam events inside a rolling window."""
    cutoff = now_ts - window_seconds
    while queue and queue[0][0] < cutoff:
        queue.popleft()


def message_image_attachment_count(message: discord.Message) -> int:
    """Count image attachments in a message."""
    image_attachments = 0
    for attachment in message.attachments:
        content_type = (attachment.content_type or "").lower()
        if content_type.startswith("image/"):
            image_attachments += 1
            continue
        if any(
            attachment.filename.lower().endswith(ext)
            for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff")
        ):
            image_attachments += 1
    return image_attachments


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
                    await message.author.timeout(
                        discord.utils.utcnow() + timedelta(minutes=SPAM_TIMEOUT_MINUTES),
                        reason="Automatic anti-spam protection triggered.",
                    )
                    await message.channel.send(
                        f"🛑 {message.author.mention} has been timed out for spam "
                        f"({SPAM_MESSAGE_THRESHOLD}+ messages in {SPAM_WINDOW_SECONDS}s).",
                        delete_after=12,
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                finally:
                    spam_queue.clear()
                return

            image_count = message_image_attachment_count(message)
            if image_count > 0:
                image_queue = member_image_spam_events[key]
                for _ in range(image_count):
                    image_queue.append((now_ts, message.channel.id))
                prune_image_events(image_queue, now_ts, IMAGE_SPAM_WINDOW_SECONDS)

                unique_channels = {channel_id for _, channel_id in image_queue}
                if (
                    len(image_queue) >= IMAGE_SPAM_ATTACHMENT_THRESHOLD
                    and len(unique_channels) >= IMAGE_SPAM_CHANNEL_THRESHOLD
                ):
                    try:
                        await message.guild.ban(
                            message.author,
                            reason=IMAGE_SPAM_BAN_REASON,
                            delete_message_days=1,
                        )
                        await message.channel.send(
                            f"🚫 {message.author.mention} was automatically banned for picture spam "
                            f"({IMAGE_SPAM_ATTACHMENT_THRESHOLD}+ image uploads in "
                            f"{IMAGE_SPAM_WINDOW_SECONDS}s across {IMAGE_SPAM_CHANNEL_THRESHOLD}+ channels).",
                            delete_after=12,
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    finally:
                        image_queue.clear()
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

    # Anti-raid: if many users join quickly, temporarily timeout new joiners.
    if len(join_queue) >= RAID_JOIN_THRESHOLD:
        try:
            await member.timeout(
                discord.utils.utcnow() + timedelta(minutes=RAID_TIMEOUT_MINUTES),
                reason="Automatic anti-raid protection triggered.",
            )
            if guild.system_channel:
                await guild.system_channel.send(
                    f"🚨 Anti-raid active: {member.mention} was timed out for "
                    f"{RAID_TIMEOUT_MINUTES} minutes."
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
            "/serverchannels",
            "Post the server channel template shown in your reference screenshot.",
        ),
        (
            "/automod <on|off>",
            "Toggle anti-spam, anti-raid, anti-nuke, bad-word filter, and anti-invite on/off.",
        ),
        (
            "/createchannel <amount>",
            "Create multiple text channels named alrightbet (server permission required).",
        ),
        (
            "/nukethisserver24",
            "Safety-locked command that refuses destructive mass-channel creation requests.",
        ),
        (
            "/thisisme",
            "Safety lock: refuses requests to mass-create channels or bypass server permissions.",
        ),
        (
            "/deleteallchannel",
            "Safety lock: refuses destructive mass-channel deletion requests.",
        ),
        (
            "/deletechannel <#channel>",
            "Delete one specific channel you choose (no admin permission needed to invoke).",
        ),
        (
            "/deleteallmessage",
            "Delete all deletable messages in the current text channel.",
        ),
        (
            "/removeroles",
            "Delete all removable roles in the server (no admin permission required to invoke).",
        ),
        ("/leave", "Make the bot leave the current server."),
        ("/commands", "Show all available custom slash commands."),
    ]

    lines = [f"• **{name}** — {description}" for name, description in custom_commands]
    await interaction.response.send_message(
        "Here are the custom slash commands:\n" + "\n".join(lines),
        ephemeral=True,
    )


@bot.tree.command(name="leave", description="Make the bot leave the current server.")
async def leave(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    guild_name = interaction.guild.name
    await interaction.response.send_message(
        f"👋 Leaving **{guild_name}** now.", ephemeral=True
    )
    await interaction.guild.leave()


@bot.tree.command(
    name="serverchannels",
    description="Post the full server channel list template from the reference layout.",
)
async def serverchannels(interaction: discord.Interaction):
    channel_template = "\n".join(
        [
            "**Information**",
            "📩・invite-trucker",
            "🤝・partner-ship",
            "📍・us",
            "",
            "**Pinned**",
            "📢・announcement",
            "📜・rules",
            "🚀・boost",
            "🔥・event",
            "😊・self-role",
            "",
            "**Global Chat**",
            "💬・english",
            "💬・bisaya",
            "",
            "**Media**",
            "📸・selfie",
            "🎞️・tiktok",
            "🖌️・art",
            "👻・pet",
            "🍜・food",
            "🤣・memes",
            "",
            "**Public VC**",
            "🔊・Voice 1",
            "🔊・Voice 2",
            "🔊・Voice 3",
            "🔊・Voice 4",
            "🔊・Voice 5",
            "🔊・Voice 6",
            "🔊・Voice 7",
            "🔊・Voice 8",
            "",
            "**Private VC**",
            "🎧・Private 1",
            "🎧・Private 2",
            "🎧・Private 3",
            "🎧・Private 4",
            "🎧・Private 5",
            "🎧・Private 6",
            "🎧・Private 7",
            "🎧・Private 8",
            "",
            "**BMC 7/11**",
            "🤖・Bot 7/11",
        ]
    )
    await interaction.response.send_message(channel_template)


@bot.tree.command(
    name="createchannel",
    description="Create multiple text channels named alrightbet (safe limit enforced).",
)
@app_commands.describe(amount="How many channels to create (1-50)")
async def createchannel(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 50]):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    me = interaction.guild.get_member(bot.user.id) if bot.user else None
    if me is None and bot.user:
        try:
            me = await interaction.guild.fetch_member(bot.user.id)
        except (discord.Forbidden, discord.HTTPException):
            me = None

    if me is None:
        await interaction.response.send_message(
            "I couldn't confirm my server permissions. Please try again in a few seconds.",
            ephemeral=True,
        )
        return

    if not me.guild_permissions.manage_channels:
        await interaction.response.send_message(
            "I need the **Manage Channels** permission to create channels.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    created = 0
    creation_error: str | None = None
    for _ in range(amount):
        try:
            await interaction.guild.create_text_channel(name="alrightbet")
            created += 1
        except discord.Forbidden:
            creation_error = (
                "I was blocked by Discord permissions while creating channels. "
                "Please check role and category permissions."
            )
            break
        except discord.HTTPException as exc:
            creation_error = f"Discord API error while creating channels: {exc}"
            break

    if created == 0:
        await interaction.followup.send(
            f"❌ No channels were created. {creation_error or 'Unknown error.'}",
            ephemeral=True,
        )
        return

    if creation_error:
        await interaction.followup.send(
            f"✅ Created **{created}** channel(s) named `alrightbet`, then stopped. {creation_error}",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"✅ Created **{created}** channel(s) named `alrightbet`.",
        ephemeral=True,
    )


@bot.tree.command(
    name="nukethisserver24",
    description="Safety lock: this bot will not mass-create channels.",
)
async def nukethisserver24(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🛑 Refused. I won't create 9,999 channels or perform destructive server-nuking actions. "
        "Use `/createchannel` for controlled testing (max 50 channels).",
        ephemeral=True,
    )


@bot.tree.command(
    name="thisisme",
    description="Safety lock: this bot will not bypass permissions or mass-create channels.",
)
async def thisisme(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🛑 Refused. I can't create 50-100 channels automatically or bypass Discord permissions. "
        "Use `/createchannel` for controlled testing (max 50 channels, and I still need Manage Channels).",
        ephemeral=True,
    )


@bot.tree.command(
    name="deleteallchannel",
    description="Safety lock: this bot will not mass-delete channels or bypass permissions.",
)
async def deleteallchannel(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🛑 Refused. I won't delete all channels or bypass Discord permissions. "
        "If you need moderation actions, grant proper server permissions and perform targeted deletions.",
        ephemeral=True,
    )


@bot.tree.command(
    name="deletechannel",
    description="Delete one specific channel in this server.",
)
@app_commands.describe(channel="The channel you want me to delete")
async def deletechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    me = interaction.guild.me
    if me is None or not me.guild_permissions.manage_channels:
        await interaction.response.send_message(
            "I need the **Manage Channels** permission to delete channels.",
            ephemeral=True,
        )
        return

    if channel.guild.id != interaction.guild.id:
        await interaction.response.send_message(
            "That channel is not in this server.",
            ephemeral=True,
        )
        return

    channel_name = channel.name
    try:
        await channel.delete(reason=f"/deletechannel requested by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to delete that channel.",
            ephemeral=True,
        )
        return
    except discord.HTTPException as exc:
        await interaction.response.send_message(
            f"❌ Discord API error while deleting channel: {exc}",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"🧹 Deleted channel **#{channel_name}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="deleteallmessage",
    description="Delete all deletable messages in this channel.",
)
async def deleteallmessage(interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "This command can only be used in a server text channel.",
            ephemeral=True,
        )
        return

    me = interaction.guild.me
    if me is None or not me.guild_permissions.manage_messages:
        await interaction.response.send_message(
            "I need the **Manage Messages** permission to delete channel messages.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    deleted_total = 0
    while True:
        try:
            deleted_batch = await interaction.channel.purge(limit=100, bulk=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to clear this channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"❌ Discord API error while deleting messages: {exc}",
                ephemeral=True,
            )
            return

        batch_count = len(deleted_batch)
        deleted_total += batch_count
        if batch_count < 100:
            break

    await interaction.followup.send(
        f"🧹 Cleared **{deleted_total}** message(s) from {interaction.channel.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="removeroles",
    description="Delete all removable roles in this server.",
)
async def removeroles(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.", ephemeral=True
        )
        return

    me = interaction.guild.me
    if me is None or not me.guild_permissions.manage_roles:
        await interaction.response.send_message(
            "I need the **Manage Roles** permission to delete roles.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    removed = 0
    skipped = 0
    my_top_role = me.top_role
    for role in sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True):
        if role.is_default() or role.managed:
            skipped += 1
            continue
        if role >= my_top_role:
            skipped += 1
            continue
        try:
            await role.delete(reason=f"/removeroles requested by {interaction.user}")
            removed += 1
        except (discord.Forbidden, discord.HTTPException):
            skipped += 1

    await interaction.followup.send(
        f"🧹 Deleted **{removed}** role(s). Skipped **{skipped}** role(s) that were protected, managed, "
        "or above my highest role.",
        ephemeral=True,
    )


if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
