from typing import Tuple, List, Dict, Any, Optional, Union
from fetch import fetch_json
import os

# Configuration
TRACKER_FILE_PATH = "tracker.txt"
ADVANCED_TRACKER_FILE_PATH = "advanced_tracker.txt"


async def get_player_data(server_id: str) -> Dict[str, Any]:
    """
    Fetch player data for a specific server

    Args:
        server_id: The server ID to fetch data for

    Returns:
        Dictionary containing server data
    """
    # Your original endpoint seems more appropriate
    server_url = f"https://api.wynncraft.com/v3/player?identifier=uuid&server={server_id}"
    return await fetch_json(server_url) or {"players": []}


async def check_player_details(player_uuid: str, target_level: int, level_range: int) -> Union[Tuple[None, List[Any]], Tuple[str, List[Dict[str, Any]]]]:
    """
    Check if a player has characters within the target level range and also check if they have deaths.

    Args:
        player_uuid: Player UUID to check
        target_level: Target level to search for
        level_range: Range around target level

    Returns:
        Tuple of (player_name, list of matching characters)
    """
    stats_url = f"https://api.wynncraft.com/v3/player/{player_uuid}?fullResult"
    player_data = await fetch_json(stats_url)

    if not player_data or "characters" not in player_data:
        return None, []

    player_name = player_data.get("username", "Unknown")
    active_character_id = player_data.get("activeCharacter", "Unknown")
    matches = []

    for cid, character in player_data.get("characters", {}).items():
        if not isinstance(character, dict):
            continue

        if "hunted" in character.get("gamemode", []):
            level = character.get("level", 0)
            if abs(level - target_level) <= level_range and cid == active_character_id:
                gamemodes = character.get("gamemode", [])

                # Fetching the number of deaths directly (from the character data)
                deaths = player_data.get("deaths")
                if deaths is None:
                    deaths = 0

                # Setting is_hich to False if deaths > 0
                is_hich = False if deaths > 0 else all(
                    mode in gamemodes for mode in ["craftsman", "hunted", "hardcore"]) and (
                                                           "ironman" in gamemodes or "ultimate_ironman" in gamemodes
                                                   )

                matches.append({
                    "player_name": player_name,
                    "character_type": character.get("type", "Unknown"),
                    "character_id": cid,
                    "level": level,
                    "is_hich": is_hich,  # Now is_hich will be False if deaths > 0
                    "gamemodes": gamemodes,
                    "deaths": deaths  # Add deaths field to the match details
                })

    return player_name, matches


async def get_tracked_players() -> List[str]:
    """
    Get list of tracked players from the tracker file

    Returns:
        List of tracked player entries (format: "name,uuid")
    """
    try:
        with open(TRACKER_FILE_PATH, "r") as f:
            return [line.strip() for line in f if line.strip() and "," in line]
    except FileNotFoundError:
        return []

async def get_advanced_tracked_players() -> List[str]:
    try:
        with open(ADVANCED_TRACKER_FILE_PATH, "r") as f:
            return [line.strip() for line in f if line.strip() and "," in line]
    except FileNotFoundError:
        return []


async def get_detail_character_data(playerName, character_uuid):
    try:
        # First try fetching via the player endpoint (which might be more stable)
        player_url = f"https://api.wynncraft.com/v3/player/{playerName}"
        player_data = await fetch_json(player_url)

        # Check if we got player data
        if player_data and "characters" in player_data:
            # Try to find the specific character by UUID
            characters = player_data.get("characters", {})
            for char_id, char_data in characters.items():
                if char_id == character_uuid:
                    combat_level = int(char_data.get("level", 0)) + (char_data.get("xpPercent", 0) * 0.01)
                    professions = char_data.get("professions", {})
                    char_class = char_data.get("type", None)

                    # Build profession string with level + xpPercent * 0.01
                    prof_levels = []
                    for prof, prof_data in professions.items():
                        level = prof_data.get("level", 0)
                        xp_percent = prof_data.get("xpPercent", 0)
                        adjusted_level = level + (xp_percent * 0.01)
                        prof_levels.append(f"{prof}:{adjusted_level:.2f}")

                    prof_levels.sort()
                    return combat_level, char_class, prof_levels

        # If we couldn't find the character via player endpoint, try direct character endpoint
        char_url = f"https://api.wynncraft.com/v3/player/{playerName}/characters/{character_uuid}"
        data = await fetch_json(char_url)

        if not data or "type" not in data:
            print(f"❌ Character data not found for {playerName}, UUID: {character_uuid}")
            return 0, "Unknown", []

        combat_level = int(data.get("level", 0)) + (data.get("xpPercent", 0) * 0.01)
        professions = data.get("professions", {})
        char_class = data.get("type", None)

        # Build profession string with level + xpPercent * 0.01
        prof_levels = []
        for prof, prof_data in professions.items():
            level = prof_data.get("level", 0)
            xp_percent = prof_data.get("xpPercent", 0)
            adjusted_level = level + (xp_percent * 0.01)
            prof_levels.append(f"{prof}:{adjusted_level:.2f}")

        prof_levels.sort()

        return combat_level, char_class, prof_levels

    except Exception as e:
        print(f"Error fetching character data for {playerName}: {e}")
        # Return default values in case of error
        return 0, "Unknown", []