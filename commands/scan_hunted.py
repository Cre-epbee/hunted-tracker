from datetime import datetime
import asyncio
from discord import Interaction
from discord import app_commands
from typing import Optional
from player_data import get_player_data, check_player_details, get_tracked_players
import os

# Configuration (from .emv)
TARGET_LEVEL = int(os.getenv("TARGET_LEVEL", "26"))
LEVEL_RANGE = int(os.getenv("LEVEL_RANGE", "10"))
SERVER_REGIONS = os.getenv("SERVER_REGIONS", "EU,NA,AS").split(",")
SERVERS_PER_REGION = int(os.getenv("SERVERS_PER_REGION", "20"))
TRACKER_FILE_PATH = "tracker.txt"


async def run_scan_hunted(
        interaction: Interaction,
        thread_executor,
        target_level: int = TARGET_LEVEL,
        level_range: int = LEVEL_RANGE):
    """
    Scan Wynncraft servers for hunted players within a specific level range

    Args:
        interaction: Discord interaction
        thread_executor: ThreadPoolExecutor for running blocking API calls
        target_level: Target level to search for
        level_range: Level range around target
    """
    # Track total matches found
    total_matches = 0
    total_hich_matches = 0
    total_players_scanned = 0

    # Initial message
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(f"Starting scan at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n" + "-" * 60)

    # Send a status message that we'll update
    status_message = await interaction.followup.send("Initialising scan...")

    # Get tracked players for HICH detection
    tracked_players = get_tracked_players()
    tracked_names = [line.split(",")[0].lower() for line in tracked_players]

    # Main logic
    for region in SERVER_REGIONS:
        for server_number in range(1, SERVERS_PER_REGION + 1):
            server_id = f"{region}{server_number}"

            # Use thread executor for API calls to prevent blocking the event loop
            server_data = await asyncio.get_event_loop().run_in_executor(
                thread_executor, get_player_data, server_id)

            # Get player count for this server
            players_in_server = len(server_data.get("players", []))
            total_players_scanned += players_in_server

            # Update status message instead of sending a new one
            await status_message.edit(content=f"Scanning server {server_id}... Found {players_in_server} players")

            # If server is empty, continue to next server
            if players_in_server == 0:
                continue

            # Data to send as final statistics
            server_matches = 0
            server_hich_matches = 0
            match_messages = []

            # Process each player in the server
            for player_uuid in server_data.get("players", []):
                # Use thread executor for API calls to prevent blocking the event loop
                player_name, matches = await asyncio.get_event_loop().run_in_executor(
                    thread_executor, check_player_details, player_uuid, target_level, level_range)

                # Process matches if any found
                for match in matches:
                    server_matches += 1
                    total_matches += 1

                    # Add HICH label if applicable
                    hich_label = ""
                    if match['is_hich']:
                        hich_label = " [HICH]"
                        server_hich_matches += 1
                        total_hich_matches += 1

                        # Track newly detected HICH/HUICH players
                        if player_name.lower() not in tracked_names:
                            with open(TRACKER_FILE_PATH, "a") as tracker_file:
                                tracker_file.write(f"{player_name},{player_uuid}\n")
                            match_messages.append(f"📝 Added new HICH/HUICH player: `{player_name}` to the tracker")
                        else:
                            match_messages.append("This HICH/HUICH is already in the tracker")

                    match_messages.append(
                        f"{interaction.user.mention} [MATCH]{hich_label} `{match['player_name']}` - Class: `{match['character_type']}`, Level: `{match['level']}` in `{server_id}`"
                    )

                # Allow other tasks to run after processing each player
                await asyncio.sleep(0)

            # Send match information if any found
            if match_messages:
                await interaction.followup.send("\n".join(match_messages))
                hich_info = f" ({server_hich_matches} HICH)" if server_hich_matches > 0 else ""
                await interaction.followup.send(
                    f"Found {server_matches} matching characters{hich_info} on {server_id}")

            # Status update every 5 servers - update the progress in the status message
            if server_number % 5 == 0:
                progress_message = f"Progress: {region} servers 1-{server_number} complete. Total players scanned: {total_players_scanned}"
                await status_message.edit(content=progress_message)

            # Allow other tasks to run after processing each server
            await asyncio.sleep(0)

    # Final statistics
    final_message = "\n" + "=" * 60 + "\n"
    final_message += f"Scan completed at `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
    final_message += f"Total players scanned: `{total_players_scanned}`\n"
    final_message += f"Total matches found: `{total_matches}`\n"
    if total_hich_matches > 0:
        final_message += f"Total HICH matches found: `{total_hich_matches}`\n"
    final_message += f"Target level: `{target_level}` (Range: `±{level_range}`)\n"
    final_message += "=" * 60

    # Update status message with completion notice
    await status_message.edit(content="Scan complete! Check results below.")

    # Send final result
    await interaction.followup.send(final_message)