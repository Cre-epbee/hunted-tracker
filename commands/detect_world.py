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
import aiofiles

from player_data import get_player_data, check_player_details, get_tracked_players, get_advanced_tracked_players, get_detail_character_data
from fetch import fetch_json
from shared_state import tracker_task, detect_world_tasks

# Configuration (from .emv)
TARGET_LEVEL = int(os.getenv("TARGET_LEVEL", "26"))
LEVEL_RANGE = int(os.getenv("LEVEL_RANGE", "10"))
SERVER_REGIONS = os.getenv("SERVER_REGIONS", "EU,NA,AS").split(",")
SERVERS_PER_REGION = int(os.getenv("SERVERS_PER_REGION", "20"))
TRACKER_FILE_PATH = "tracker.txt"
ADVANCED_TRACKER_FILE_PATH = "advaced_tracker.txt"

async def run_detect_world(
interaction: discord.Interaction,
        world: str,
        level: int = TARGET_LEVEL,
        level_range: int = LEVEL_RANGE,
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
        new_tracked = []
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
                    server_data = await get_player_data(world)

                    if not server_data or "players" not in server_data:
                        await interaction.followup.send(f"⚠️ No data found for world `{world}`.")
                        break

                    tracked_players = await get_advanced_tracked_players()
                    tracked_names = {line.split(",")[0].lower() for line in tracked_players}

                    match_messages = []
                    server_matches = 0

                    for player_uuid in server_data.get("players", []):
                        player_name, matches = await check_player_details(player_uuid, level, level_range)

                        for match in matches:
                            server_matches += 1
                            is_hich = match["is_hich"]
                            match_messages.append(
                                f"`{match['player_name']}`{' [HICH]' if is_hich else ''} - "
                                f"Class: `{match['character_type']}`, Level: `{match['level']}`"
                            )

                            character_uuid = match['character_id']
                            if is_hich and player_name.lower() not in tracked_names:
                                combat_level, char_class, prof_levels = await get_detail_character_data(player_uuid,character_uuid)
                                new_tracked.append(
                                    f"{player_name},{char_class},{uuid},{character_uuid},combat:{combat_level:.2f}," + ",".join(
                                        prof_levels) + "\n")

                        if new_tracked:
                            async with aiofiles.open(TRACKER_FILE_PATH, "a") as f:
                                f.write(new_tracked)

                        await asyncio.sleep(0)  # Yield control after each player

                    if match_messages:
                        await interaction.followup.send(
                            f"📝 **Found {server_matches} hunted players in `{world}`:**\n" +
                            "\n".join(match_messages)
                        )
                    else:
                        if not interval:
                            await interaction.followup.send(
                                f"⛔ No level `{level}±{level_range}` hunted players found in `{world}`.")
                        else:
                            print(f"⛔ No hunted players found in `{world}`.")  # Debugging purposes

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