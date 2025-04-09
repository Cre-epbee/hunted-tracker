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
from responses import get_response
from concurrent.futures import ThreadPoolExecutor
from ratelimit import limits, sleep_and_retry
import importlib

# Import separated command modules
from commands.hello import run_hello
from commands.scan_hunted import run_scan_hunted
from commands.tracker import  run_tracker
from player_data import get_player_data, check_player_details, get_tracked_players
from fetch import fetch_json
from shared_state import tracker_task, detect_world_tasks

# Configuration
TARGET_LEVEL = int(os.getenv("TARGET_LEVEL", "26"))
LEVEL_RANGE = int(os.getenv("LEVEL_RANGE", "10"))
SERVER_REGIONS = os.getenv("SERVER_REGIONS", "EU,NA,AS").split(",")
SERVERS_PER_REGION = int(os.getenv("SERVERS_PER_REGION", "20"))
CALLS = int(os.getenv("CALLS", "95"))
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


# Message functionality
async def send_message(message: Message, user_message: str) -> None:
    if not user_message:
        print('(Message was empty because intents were not enabled probably)')
        return

    is_private = user_message[0] == '?'
    if is_private:
        user_message = user_message[1:]

    try:
        response: str = get_response(user_message)
        if is_private:
            await message.author.send(response)
        else:
            await message.channel.send(response)
    except Exception as e:
        print(f"Error sending message: {e}")


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
    await run_scan_hunted(interaction, thread_executor, target_level, level_range)


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
    interval="How often (in seconds) to scan the world (leave empty for a one-time scan)",
    stop="Set to True to stop a running detect-world task for the specified world"
)
async def detect_world(
        interaction: discord.Interaction,
        world: str,
        level: int = TARGET_LEVEL,
        interval: Optional[int] = None,
        stop: Optional[bool] = None,
):
    global detect_world_tasks

    # Handle task stop
    if stop:
        task = detect_world_tasks.get(world)
        if task and not task.done():
            task.cancel()
            del detect_world_tasks[world]
            await interaction.response.send_message(f"🛑 World tracker for `{world}` stopped.")
        else:
            await interaction.response.send_message(f"⚠️ No active tracker found for world `{world}`.")
        return

    # Prevent duplicate tasks
    if world in detect_world_tasks and not detect_world_tasks[world].done():
        await interaction.response.send_message(
            f"⚠️ World `{world}` is already being tracked. Use `/detect-world world:{world} stop:True` to stop it first."
        )
        return

    await interaction.response.defer(thinking=True)

    async def world_tracker_loop():
        try:
            scan_count = 0
            status_message = None

            while True:
                scan_count += 1
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # First-time or updated status
                content = f"🔍 Scanning world `{world}` (Scan #`{scan_count}`) at `{timestamp}`"
                if interval:
                    try:
                        if status_message:
                            await status_message.edit(content=content)
                        else:
                            status_message = await interaction.followup.send(content)
                    except discord.HTTPException:
                        status_message = await interaction.followup.send(content)

                try:
                    server_data = await asyncio.get_event_loop().run_in_executor(
                        thread_executor, get_player_data, world
                    )

                    if not server_data or "players" not in server_data:
                        await interaction.followup.send(f"⚠️ No data found for world `{world}`.")
                        break

                    tracked_players = get_tracked_players()
                    tracked_names = {line.split(",")[0].lower() for line in tracked_players}

                    match_messages = []
                    server_matches = 0

                    for player_uuid in server_data.get("players", []):
                        player_name, matches = await asyncio.get_event_loop().run_in_executor(
                            thread_executor, check_player_details, player_uuid, level, LEVEL_RANGE
                        )

                        for match in matches:
                            server_matches += 1
                            is_hich = match["is_hich"]
                            match_messages.append(
                                f"`{match['player_name']}`{' [HICH]' if is_hich else ''} - "
                                f"Class: `{match['character_type']}`, Level: `{match['level']}`"
                            )

                            if is_hich and player_name.lower() not in tracked_names:
                                with open(TRACKER_FILE_PATH, "a") as f:
                                    f.write(f"{player_name},{player_uuid}\n")
                                tracked_names.add(player_name.lower())

                        await asyncio.sleep(0)  # Yield control after each player

                    if match_messages:
                        await interaction.followup.send(
                            f"📝 **Found {server_matches} hunted players in `{world}`:**\n" +
                            "\n".join(match_messages)
                        )
                    else:
                        if not interval:
                            await interaction.followup.send(
                                f"⛔ No level `{level}-Ranged` hunted players found in `{world}`.")
                        else:
                            print(f"⛔ No hunted players found in `{world}`.")  #Debugging purposes

                except Exception as e:
                    await interaction.followup.send(f"⚠️ Error scanning world `{world}`: {e}")
                    print(f"[ERROR] World scan error ({world}):", e)

                if not interval:
                    break

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            print(f"[INFO] Tracker for world {world} was cancelled.")
            await interaction.followup.send(f"🛑 World tracker for `{world}` stopped.")
        except Exception as e:
            await interaction.followup.send(f"⚠️ Unexpected error in world tracker `{world}`: {e}")
            print(f"[CRITICAL] Tracker loop error ({world}):", e)
        finally:
            detect_world_tasks.pop(world, None)

    # Start the tracking loop
    if interval:
        await interaction.followup.send(f"🔁 Starting to track world `{world}` every `{interval}` seconds.")
    detect_world_tasks[world] = asyncio.create_task(world_tracker_loop())


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
    await interaction.response.defer(thinking=True)

    try:
        HICH_leaderboard_url = "https://api.wynncraft.com/v3/leaderboards/hichContent"
        leaderboard_data = fetch_json(HICH_leaderboard_url)

        if not isinstance(leaderboard_data, dict) or not leaderboard_data:
            await interaction.followup.send("⚠️ Failed to retrieve leaderboard data.")
            return

        tracked_players = get_tracked_players()
        tracked_names = {line.split(",")[0].lower() for line in tracked_players}
        new_tracked = []
        matched_players = []

        for _, entry in leaderboard_data.items():
            player_name = entry.get("name", "Unknown")
            uuid = entry.get("uuid", "")
            character_type = entry.get("characterType", "Unknown")
            character_type = character_type.upper()
            character_data = entry.get("characterData", {})

            level_value = character_data.get("level", 0)
            deaths = character_data.get("deaths", 0)

            # Skip players with deaths
            if deaths > 0:
                continue

            # Match based on level range
            if level - hunted_range <= level_value <= level + hunted_range:
                matched_players.append(
                    f"`{player_name}` - Level: `{level_value}` - Class: `{character_type}`"
                )

                # Add to tracker if not already tracked
                if player_name.lower() not in tracked_names:
                    new_tracked.append(f"{player_name},{uuid}\n")
                    tracked_names.add(player_name.lower())

        # Append new entries to the tracker file
        if new_tracked:
            with open(TRACKER_FILE_PATH, "a") as f:
                f.writelines(new_tracked)

        if matched_players:
            await interaction.followup.send(
                f"📝 **Found {len(matched_players)} deathless HICH players in level range `{level} ± {hunted_range}`:**\n" +
                "\n".join(matched_players)
            )
        else:
            await interaction.followup.send(
                f"⛔ No deathless HICH players found within level range `{level} ± {hunted_range}`.")

    except Exception as e:
        await interaction.followup.send(f"⚠️ Error while checking HICH leaderboard: {e}")


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
    global tracker_task, detect_world_tasks

    active_count = 0
    tracker_status = "❌ No player tracker running"

    if tracker_task and not tracker_task.done():
        active_count += 1
        tracker_status = "✅ Player tracker is running"

    world_trackers = []
    for world, task in list(detect_world_tasks.items()):
        if not task.done():
            world_trackers.append(f"- World `{world}`")
            active_count += 1

    # Handle stopping all trackers if requested
    if stop_all:
        stop_count = 0

        # Stop the player tracker if running
        if tracker_task and not tracker_task.done():
            tracker_task.cancel()
            tracker_task = None
            stop_count += 1

        # Stop all world trackers
        for world, task in list(detect_world_tasks.items()):
            if not task.done():
                task.cancel()
                del detect_world_tasks[world]
                stop_count += 1

        await interaction.response.send_message(f"🛑 Stopped {stop_count} active tracker(s).")
        return

    # Otherwise just list the active trackers
    if active_count == 0:
        await interaction.response.send_message("🔍 No active trackers running.")
    else:
        response = f"🔍 **{active_count} Active Tracker(s):**\n\n{tracker_status}"

        if world_trackers:
            response += "\n\n**World Trackers:**\n" + "\n".join(world_trackers)

        response += "\n\nUse `/active-trackers stop_all:True` to stop all trackers."
        await interaction.response.send_message(response)


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
