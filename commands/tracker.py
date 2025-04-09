from datetime import datetime
import asyncio
import discord
from discord import Interaction
from discord import app_commands
from typing import Optional
from player_data import get_player_data, check_player_details, get_tracked_players
import os
from shared_state import tracker_task, detect_world_tasks
from fetch import fetch_json

# Configuration (from .env)
TARGET_LEVEL = int(os.getenv("TARGET_LEVEL", "26"))
LEVEL_RANGE = int(os.getenv("LEVEL_RANGE", "10"))
SERVER_REGIONS = os.getenv("SERVER_REGIONS", "EU,NA,AS").split(",")
SERVERS_PER_REGION = int(os.getenv("SERVERS_PER_REGION", "20"))
TRACKER_FILE_PATH = "tracker.txt"

async def run_tracker(interaction:discord.Interaction,
                      add,
                      remove,
                      list_players,
                      find,
                      interval,
                      stop):

    global tracker_task

    # Enforce only one main action at a time
    if sum(bool(arg) for arg in [add, remove, list_players, find, stop]) != 1:
        await interaction.response.send_message("⚠️ Use exactly one of: `add`, `remove`, `list`, `find`, or `stop`.")
        return

    if interval and not find:
        await interaction.response.send_message("⚠️ `interval` is only valid with `find=True`.")
        return

    # Add player (Not case-sensitve)
    if add:
        stats_url = f"https://api.wynncraft.com/v3/player/{add}?fullResult"
        player_data = fetch_json(stats_url)

        if not player_data:
            await interaction.response.send_message(f"❌ Could not find player `{add}` or API request failed.")
            return

        tracker_uuid = player_data.get("uuid")

        if tracker_uuid:
            # Read current tracked players to check for duplicates
            already_tracked = False
            with open(TRACKER_FILE_PATH, "r") as f:
                for line in f:
                    if line.lower().startswith(add.lower() + ","):
                        already_tracked = True
                        break

            if already_tracked:
                await interaction.response.send_message(f"❌ `{add}` is already in the tracker.")
            else:
                with open(TRACKER_FILE_PATH, "a") as f:
                    f.write(f"{add},{tracker_uuid}\n")
                await interaction.response.send_message(f"✅ Added `{add}` to the tracker.")
        else:
            await interaction.response.send_message(f"❌ Could not find player `{add}`.")

    # Remove player (again, not case-sensitive)
    elif remove:
        updated_lines = []
        found = False

        try:
            # Check if the player is in the list
            with open(TRACKER_FILE_PATH, "r") as f:
                for line in f:
                    if not line.lower().startswith(remove.lower() + ","):
                        updated_lines.append(line)
                    else:
                        found = True

            with open(TRACKER_FILE_PATH, "w") as f:
                f.writelines(updated_lines)

            if found:
                await interaction.response.send_message(f"🗑️ Removed `{remove}` from the tracker.")
            else:
                await interaction.response.send_message(f"⚠️ Player `{remove}` not found in tracker.")

        except FileNotFoundError:
            await interaction.response.send_message("⚠️ Tracker file not found. Creating new file.")
            open(TRACKER_FILE_PATH, "w").close()

    # List all tracked players
    elif list_players:
        try:
            # Now read it line by line
            player_names = []
            with open(TRACKER_FILE_PATH, "r") as f:
                for line_number, line in enumerate(f, 1):
                    line = line.strip()
                    # print(f"Processing line {line_number}: {repr(line)}") Debugging purposes
                    if "," in line:
                        player_name = line.split(",")[0]
                        player_names.append(player_name)
                        # print(f"Added player: {player_name}") Debugging purposes

            # If the tracker is empty
            if not player_names:
                await interaction.response.send_message("📭 No players currently tracked.")
            else:
                tracked = "\n".join(player_names)
                await interaction.response.send_message(
                    f"📝 **Currently Tracked Players ({len(player_names)}):**\n```\n{tracked}\n```")

        except FileNotFoundError:
            await interaction.response.send_message("⚠️ Tracker file not found.")
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Error listing tracked players: {e}")
            print(f"Error in tracker list: {e}")

    # Stop tracker loop
    elif stop:
        if tracker_task and not tracker_task.done():
            tracker_task.cancel()
            tracker_task = None
            await interaction.response.send_message("🛑 Tracker loop stopped.")
        else:
            await interaction.response.send_message("⚠️ No tracker is currently running.")

    # Find online hunted players (optionally looped)
    elif find:
        if tracker_task and not tracker_task.done():
            await interaction.response.send_message("⚠️ Tracker is already running. Use `/tracker stop` to end it.")
            return

        await interaction.response.send_message("🔍 Starting tracker..." + (f" Every {interval}s." if interval else ""))

        async def tracker_loop():
            try:
                while True:
                    player_names = []
                    with open(TRACKER_FILE_PATH, "r") as f:
                        for line in f:
                            line = line.strip()
                            if "," in line:
                                parts = line.split(",", 1)
                                if len(parts) == 2:
                                    tracked_name, player_uuid = parts
                                    player_names.append((tracked_name, player_uuid))

                    found_match = False  # 🔍 Track if any hunted players are found

                    for tracked_name, player_uuid in player_names:
                        stats_url = f"https://api.wynncraft.com/v3/player/{player_uuid}?fullResult"
                        player_data = fetch_json(stats_url)

                        if not player_data or "characters" not in player_data:
                            continue

                        actual_name = player_data.get("username", "").lower()
                        if actual_name != tracked_name.lower():
                            continue

                        online = player_data.get("online", None)
                        active_character = player_data.get("activeCharacter", None)
                        online_server = player_data.get("server", None)

                        character_data = player_data.get("characters", {}).get(active_character, {})

                        if (
                                online is True and
                                "hunted" in character_data.get("gamemode", [])
                        ):
                            found_match = True
                            level = character_data.get("level", 0)
                            class_type = character_data.get("type", "Unknown")

                            await interaction.followup.send(
                                f"{interaction.user.mention} 🧭 `{tracked_name}` is online in `{online_server}` "
                                f"on a Hunted **{class_type}**, level **{level}**!"
                            )

                    # ✅ If not looping and nothing was found, notify the user
                    if not interval:
                        if not found_match:
                            await interaction.followup.send("⛔ No hunted players are currently online.")
                        break

                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                print("Tracker loop was cancelled")
            except Exception as e:
                await interaction.followup.send(f"⚠️ Tracker loop encountered an error: {e}")
                print(f"Tracker error: {e}")

        tracker_task = asyncio.create_task(tracker_loop())