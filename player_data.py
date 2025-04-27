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


async def check_player_details(player_uuid: str, target_level: int, level_range: int) -> Union[
    Tuple[None, List[Any]], Tuple[str, List[Dict[str, Any]]]]:
    """
    Check if a player's active character is within the target level range and
    has "hunted" gamemode or completed "A Hunter's Calling".

    Returns:
        (player_name, matches)
    """
    stats_url = f"https://api.wynncraft.com/v3/player/{player_uuid}?fullResult"
    player_data = await fetch_json(stats_url)

    if not player_data or "characters" not in player_data:
        return None, []

    player_name = player_data.get("username", "Unknown")
    active_character_id = player_data.get("activeCharacter")
    matches = []

    if not active_character_id or active_character_id not in player_data.get("characters", {}):
        return player_name, []

    character = player_data["characters"][active_character_id]

    level = character.get("level", 0)
    gamemodes = character.get("gamemode", [])
    deaths = character.get("deaths") or 0  # Safe fallback if deaths=None
    quests = character.get("quests", [])

    # Check conditions
    is_in_level_range = abs(level - target_level) <= level_range
    has_hunted_gamemode = "hunted" in gamemodes
    has_hunters_calling = "A Hunter's Calling" in quests

    toggle_hunted = has_hunters_calling

    # Determine HICH status (strictly requiring all 4 gamemodes)
    is_hich = False
    if deaths == 0:
        required_modes = {"craftsman", "hunted", "hardcore", "ironman"}
        if required_modes.issubset(set(gamemodes)):
            is_hich = True

    # If hunted or has completed the quest and within level range
    if (has_hunted_gamemode or has_hunters_calling) and is_in_level_range:
        matches.append({
            "player_name": player_name,
            "character_type": character.get("type", "Unknown"),
            "character_id": active_character_id,
            "level": level,
            "is_hich": is_hich,
            "gamemodes": gamemodes,
            "deaths": deaths,
            "toggleHunted": toggle_hunted
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