from asyncio import get_event_loop
from typing import Final, Any, Optional
import os
import discord
from requests import get, RequestException
import time
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from discord import Intents, Message, app_commands
from discord.ext import commands
from commands.scan_hunted import run_scan_hunted
from concurrent.futures import ThreadPoolExecutor
from ratelimit import limits, sleep_and_retry
import importlib

# Import separated command modules
from commands.hello import run_hello
from commands.scan_hunted import run_scan_hunted
from commands.tracker import  run_tracker
from commands.detect_world import run_detect_world
from commands.sync_leaderboard import run_sync_leaderboard
from commands.active_trackers import run_active_trackers
from player_data import get_player_data, check_player_details, get_tracked_players
from fetch import fetch_json
from shared_state import tracker_task, detect_world_tasks

# Configuration
TARGET_LEVEL = int(os.getenv("TARGET_LEVEL", "26"))
LEVEL_RANGE = int(os.getenv("LEVEL_RANGE", "10"))
SERVER_REGIONS = os.getenv("SERVER_REGIONS", "EU,NA,AS").split(",")
SERVERS_PER_REGION = int(os.getenv("SERVERS_PER_REGION", "20"))
CALLS = int(os.getenv("CALLS", "95")) #Adjust this if needed
PERIOD = int(os.getenv("PERIOD", "60"))
TRACKER_FILE_PATH = "tracker.txt"


# Create tracker file if it doesn't exist
if not os.path.exists(TRACKER_FILE_PATH):
    open(TRACKER_FILE_PATH, "w").close()

# Load environment variables and set up the bot
load_dotenv()
TOKEN: Final[str] = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    raise ValueError("No Discord token found in environment variables!")

# Bot setup
intents: Intents = Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="e.gg", intents=intents)

# Create a thread executor for running blocking code
thread_executor = ThreadPoolExecutor(max_workers=5)  # Increased from 1 for better performance


# Handle bot startup
@client.event
async def on_ready() -> None:
    print(f'{client.user} is now running!')
    try:
        synced = await client.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")



# Basic slash command for testing
@client.tree.command(name="hello", description="Say hello")
async def hello(interaction: discord.Interaction):
    await run_hello(interaction)


# Wynncraft scanner command - modified to use the separate module
@client.tree.command(name="scan-hunted",
                     description="Scan Wynncraft servers for hunted players within a specific level range")
@app_commands.describe(
    target_level="Target level to search for (default: 26)",
    level_range="Level range around target (default: 10)"
)
async def scan_hunted(
        interaction: discord.Interaction,
        target_level: int = TARGET_LEVEL,
        level_range: int = LEVEL_RANGE):
    # Call the imported function, passing the thread_executor
    await run_scan_hunted(interaction, target_level, level_range)


# Update the tracker command to handle its own task
@client.tree.command(name="tracker", description="Add, remove, list, find or stop tracked hunted players.")
@app_commands.describe(
    add="Add a player to the tracker by name",
    remove="Remove a player from the tracker by name",
    list_players="List all currently tracked players",
    find="Find if tracked players are online with hunted class",
    interval="How often (in seconds) to check for hunted players (only with 'find')",
    stop="Stop the currently running tracker scan"
)
async def tracker(
        interaction: discord.Interaction,
        add: Optional[str] = None,
        remove: Optional[str] = None,
        list_players: Optional[bool] = None,
        find: Optional[bool] = None,
        interval: Optional[int] = None,
        stop: Optional[bool] = None
):
    await run_tracker(interaction, add, remove, list_players, find, interval, stop)


@client.tree.command(
    name="detect-world",
    description="Find a list of active hunters in the specified world"
)
@app_commands.describe(
    world="Enter your world number (e.g. EU1, NA2, AS3)",
    level="Your combat level (Default is 26)",
    level_range="Level range around target (default: 10)",
    interval="How often (in seconds) to scan the world (leave empty for a one-time scan)",
    stop="Set to True to stop a running detect-world task for the specified world"
)
async def detect_world(
        interaction: discord.Interaction,
        world: str,
        level: int = TARGET_LEVEL,
        level_range: int = LEVEL_RANGE,
        interval: Optional[int] = None,
        stop: Optional[bool] = None,
):
    await run_detect_world(interaction, world, level, level_range, interval, stop)


@client.tree.command(
    name="sync-leaderboard",
    description="Check HICH leaderboard and update tracker with players"
)
@app_commands.describe(
    level="Target level (Default is 26)",
    hunted_range="Target level Range (Default is 10)"
)
async def sync_leaderboard(interaction: discord.Interaction,
                           level: Optional[int] = TARGET_LEVEL,
                           hunted_range: Optional[int] = LEVEL_RANGE):
    await run_sync_leaderboard(interaction, level, hunted_range)


# Add a command to see all active world trackers and optionally stop them all
@client.tree.command(
    name="active-trackers",
    description="List all active trackers and optionally stop them all"
)
@app_commands.describe(
    stop_all="Set to True to stop all running trackers (/active-trackers stop_all:False would list the enabled trackers)")
async def active_trackers(
        interaction: discord.Interaction,
        stop_all: Optional[bool] = None):
    await run_active_trackers(interaction, stop_all)


@client.tree.command(name="help", description="List all available commands")
async def help_command(interaction: discord.Interaction):
    commands = [
        "`/hello` - Test if the bot is responding",
        "`/scan_hunted` - Scan for hunted players in a level range",
        "`/tracker` - Manage tracked players (add, remove, list, find, stop)",
        "`/detect-world` - Track hunted players in a specific world",
        "`/sync-leaderboard` - Sync with HICH leaderboard",
        "`/active-trackers` - List or stop all active trackers"
    ]

    await interaction.response.send_message(
        "**Available Commands:**\n\n" + "\n".join(commands)
    )


# Handle incoming messages
@client.event
async def on_message(message: Message) -> None:
    # Prevent the bot from responding to its own messages
    if message.author == client.user:
        return

    # Let commands be processed first
    await client.process_commands(message)

    # Only then check for regular messages
    username: str = str(message.author)
    user_message: str = message.content
    channel: str = str(message.channel)

    print(f'[{channel}] {username}: "{user_message}"')
    await send_message(message, user_message)


# Main entry point
def main() -> None:
    try:
        client.run(token=TOKEN)
    except Exception as e:
        print(f"Fatal error running bot: {e}")


if __name__ == '__main__':
    main()
