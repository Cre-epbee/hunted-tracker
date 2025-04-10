from datetime import datetime
import asyncio
import discord
from discord import Interaction
from typing import Optional
from player_data import get_player_data, check_player_details, get_tracked_players, get_advanced_tracked_players
import os
from shared_state import tracker_task
from fetch import fetch_json  # This must be an async function using aiohttp
import aiofiles

# Configuration
TARGET_LEVEL = int(os.getenv("TARGET_LEVEL", "26"))
LEVEL_RANGE = int(os.getenv("LEVEL_RANGE", "10"))
TRACKER_FILE_PATH = "tracker.txt"
ADVANCED_TRACKER_FILE_PATH = "advanced_tracker.txt"



async def run_tracker(
    interaction: Interaction,
    add: Optional[str],
    remove: Optional[str],
    list_players: Optional[bool],
    find: Optional[bool],
    interval: Optional[int],
    stop: Optional[bool],
):
    global tracker_task
    await interaction.response.defer(thinking=True)


    # Ensure only one action is provided
    if sum(bool(arg) for arg in [add, remove, list_players, find, stop]) != 1:
        await interaction.followup.send("⚠️ Use exactly one of: `add`, `remove`, `list`, `find`, or `stop`.")
        return

    if interval and not find:
        await interaction.followup.send("⚠️ `interval` is only valid with `find=True`.")
        return




    # ✅ Add
    if add:
        stats_url = f"https://api.wynncraft.com/v3/player/{add}?fullResult"
        player_data = await fetch_json(stats_url)
        if not player_data:
            await interaction.followup.send(f"❌ Could not find player `{add}` or API failed.")
            return

        uuid = player_data.get("uuid")
        if not uuid:
            await interaction.followup.send(f"❌ UUID not found for `{add}`.")
            return

        with open(TRACKER_FILE_PATH, "r+") as f:
            lines = f.readlines()
            if any(line.lower().startswith(f"{add.lower()},") for line in lines):
                await interaction.followup.send(f"⚠️ `{add}` is already in the tracker.")
                return
            f.write(f"{add},{uuid}\n")
        await interaction.followup.send(f"✅ `{add}` added to tracker.")

    # ✅ Remove
    elif remove:
        try:
            with open(TRACKER_FILE_PATH, "r") as f:
                lines = f.readlines()

            updated = [line for line in lines if not line.lower().startswith(remove.lower() + ",")]

            if len(updated) == len(lines):
                await interaction.followup.send(f"⚠️ `{remove}` not found.")
            else:
                with open(TRACKER_FILE_PATH, "w") as f:
                    f.writelines(updated)
                await interaction.followup.send(f"🗑️ `{remove}` removed from tracker.")

        except FileNotFoundError:
            await interaction.followup.send("⚠️ Tracker file not found.")

    # ✅ List
    elif list_players:
        try:
            with open(TRACKER_FILE_PATH, "r") as f:
                lines = [line.strip().split(",")[0] for line in f if "," in line]

            if not lines:
                await interaction.followup.send("📭 No tracked players.")
            else:
                await interaction.followup.send(
                    f"📝 **Currently Tracked Players ({len(lines)}):**\n```\n" + "\n".join(lines) + "\n```"
                )
        except Exception as e:
            await interaction.followup.send(f"⚠️ Error reading tracker: `{e}`")

    # ✅ Stop
    elif stop:
        if tracker_task and not tracker_task.done():
            tracker_task.cancel()
            tracker_task = None
            await interaction.followup.send("🛑 Tracker loop stopped.")
        else:
            await interaction.followup.send("⚠️ No tracker is currently running.")

    # ✅ Find (with or without interval)
    elif find:
        if tracker_task and not tracker_task.done():
            await interaction.followup.send("⚠️ Tracker is already running. Use `/tracker stop` to stop it.")
            return

        await interaction.followup.send("🔍 Starting tracker..." + (f" Every {interval}s." if interval else ""))

        async def tracker_loop():
            try:
                while True:
                    found_any = False
                    async with aiofiles.open(TRACKER_FILE_PATH, "r") as f:
                        lines = await f.readlines()

                    for line in lines:
                        line = line.strip()
                        if not line or "," not in line:
                            continue

                        name, uuid = line.split(",", 1)
                        url = f"https://api.wynncraft.com/v3/player/{uuid}?fullResult"
                        data = await fetch_json(url)

                        if not data or "characters" not in data:
                            continue

                        if data.get("username", "").lower() != name.lower():
                            continue

                        active_char = data.get("activeCharacter")
                        char_data = data.get("characters", {}).get(active_char, {})

                        if data.get("online") and "hunted" in char_data.get("gamemode", []):
                            found_any = True
                            level = char_data.get("level", 0)
                            class_type = char_data.get("type", "Unknown")
                            server = data.get("server", "Unknown")

                            await interaction.followup.send(
                                f"{interaction.user.mention} 🧭 `{name}` is online in `{server}` "
                                f"on a Hunted **{class_type}**, level **{level}**!"
                            )

                    if not interval:
                        if not found_any:
                            await interaction.followup.send("⛔ No hunted players currently online.")
                        break

                    await asyncio.sleep(interval)

            except asyncio.CancelledError:
                await interaction.followup.send("🛑 Tracker loop was cancelled.")
            except Exception as e:
                await interaction.followup.send(f"⚠️ Error in tracker loop: {e}")

        tracker_task = asyncio.create_task(tracker_loop())
