from asyncio import get_event_loop
from typing import Final, Any, Optional
import os
import discord
from requests import get, RequestException
import asyncio
from dotenv import load_dotenv
from discord import Intents, Message, app_commands
from discord.ext import commands
from commands.scan_hunted import run_scan_hunted
from concurrent.futures import ThreadPoolExecutor
from ratelimit import limits, sleep_and_retry
import importlib

from player_data import get_player_data, check_player_details, get_tracked_players
from fetch import fetch_json
from shared_state import tracker_task, detect_world_tasks

# Configuration (from .emv)
TARGET_LEVEL = int(os.getenv("TARGET_LEVEL", "26"))
LEVEL_RANGE = int(os.getenv("LEVEL_RANGE", "10"))
SERVER_REGIONS = os.getenv("SERVER_REGIONS", "EU,NA,AS").split(",")
SERVERS_PER_REGION = int(os.getenv("SERVERS_PER_REGION", "20"))
TRACKER_FILE_PATH = "tracker.txt"


async def run_sync_leaderboard(interaction: discord.Interaction,
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