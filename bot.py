import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Initialize bot with default intents
# Note: To use prefix commands like !ping, you MUST enable "Message Content Intent" 
# in the Discord Developer Portal (Applications -> Your Bot -> Bot -> Privileged Gateway Intents)
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')

@bot.command()
async def ping(ctx):
    """Responds with Pong!"""
    await ctx.send('Pong!')

@bot.command()
async def echo(ctx, *, message):
    """Echoes back the message provided."""
    await ctx.send(message)

if __name__ == '__main__':
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
