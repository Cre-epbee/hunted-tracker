import discord
import aiofiles
from discord import app_commands, Interaction
from typing import Optional
from fetch import fetch_json
import textwrap
from player_data import get_advanced_tracked_players, get_detail_character_data
import asyncio
import aiohttp

ADVANCED_TRACKER_FILE_PATH = "advanced_tracker.txt"
advanced_compare_tasks = {}

async def run_advanced_tracker(interaction: discord.Interaction,
    add: Optional[str] = None,
    char_uuid: Optional[str] = None,
    remove: Optional[str] = None,
    list_entries: Optional[bool] = None,
    compare: Optional[bool] = None,
    interval: Optional[int] = None,
    stop:Optional[bool] = None):

    await interaction.response.defer(thinking=True)


    # Only one action allowed
    if sum(bool(x) for x in [add, remove, list_entries,compare]) != 1:
        await interaction.followup.send("⚠️ Use one of: `add`, `remove`, or `list_entries=True`.")
        return

    if add:
        if not char_uuid:
            await interaction.followup.send("⚠️ You must provide the character UUID with `char_uuid`.")
            return

        # 1. Get player UUID from base endpoint
        profile_url = f"https://api.wynncraft.com/v3/player/{add}?fullResult"
        profile_data = await fetch_json(profile_url)

        if not profile_data or "uuid" not in profile_data:
            await interaction.followup.send(f"❌ Failed to fetch UUID for `{add}`.")
            return

        player_uuid = profile_data["uuid"]

        # 2. Get character data
        combat_level, char_class, prof_levels =  await get_detail_character_data(add,char_uuid)

        line = f"{add},{char_class},{player_uuid},{char_uuid},combat:{combat_level:.2f}," + ",".join(prof_levels) + "\n"

        try:
            async with aiofiles.open(ADVANCED_TRACKER_FILE_PATH, "a") as f:
                await f.write(line)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to write to file: {e}")
            return

        await interaction.followup.send(
            f"✅ Tracked `{add}` (character UUID: `{char_uuid}`) with Combat level `{combat_level:.2f}`"
        )

    elif remove:
        try:
            async with aiofiles.open(ADVANCED_TRACKER_FILE_PATH, "r") as f:
                lines = await f.readlines()

            updated = [line for line in lines if not line.lower().startswith(remove.lower() + ",")]

            async with aiofiles.open(ADVANCED_TRACKER_FILE_PATH, "w") as f:
                await f.writelines(updated)

            await interaction.followup.send(f"🗑️ Removed `{remove}` from tracked characters.")
        except Exception as e:
            await interaction.followup.send(f"⚠️ Error removing entry: {e}")

    elif list_entries:
        try:
            async with aiofiles.open(ADVANCED_TRACKER_FILE_PATH, "r") as f:
                lines = await f.readlines()

            if not lines:
                await interaction.followup.send("📭 No tracked characters.")
                return

            all_rows = []

            for line in lines:
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue

                player = parts[0]
                character_class = parts[1]
                profs = dict(item.split(":") for item in parts[4:] if ":" in item)

                fishing = float(profs.get("fishing", 0))
                mining = float(profs.get("mining", 0))
                woodcutting = float(profs.get("woodcutting", 0))
                farming = float(profs.get("farming", 0))

                avg = (fishing + mining + woodcutting + farming) / 4

                row = {
                    "Player": player,
                    "Class": character_class,
                    "Combat": profs.get("combat", "N/A"),
                    "Fishing": fishing,
                    "Mining": mining,
                    "Woodcutting": woodcutting,
                    "Farming": farming,
                    "Prof Average": f"{avg:.2f}"
                }

                all_rows.append(row)

            col_headers = ["Player", "Class", "Combat", "Fishing", "Mining", "Woodcutting", "Farming", "Prof Average"]
            col_widths = {col: max(len(col), max(len(str(row[col])) for row in all_rows)) for col in col_headers}
            header_line = " | ".join(col.ljust(col_widths[col]) for col in col_headers)
            separator = "-+-".join("-" * col_widths[col] for col in col_headers)

            # Paginate
            pages = []
            chunk_size = 10

            for i in range(0, len(all_rows), chunk_size):
                chunk = all_rows[i:i + chunk_size]
                data_lines = [
                    " | ".join(str(row[col]).ljust(col_widths[col]) for col in col_headers)
                    for row in chunk
                ]
                table = "\n".join([header_line, separator] + data_lines)
                pages.append(f"```text\n{table}\nPage {i // chunk_size + 1}/{(len(all_rows) + chunk_size - 1) // chunk_size}\n```")

            page = 0
            msg = await interaction.followup.send(pages[page], wait=True)

            await msg.add_reaction("⬅️")
            await msg.add_reaction("➡️")

            def check(reaction, user):
                return (
                    user == interaction.user
                    and reaction.message.id == msg.id
                    and str(reaction.emoji) in ["⬅️", "➡️"]
                )

            while True:
                try:
                    reaction, user = await interaction.client.wait_for("reaction_add", timeout=60.0, check=check)

                    if str(reaction.emoji) == "➡️" and page < len(pages) - 1:
                        page += 1
                    elif str(reaction.emoji) == "⬅️" and page > 0:
                        page -= 1

                    await msg.edit(content=pages[page])
                    await msg.clear_reactions()
                    await msg.add_reaction("⬅️")
                    await msg.add_reaction("➡️")

                except asyncio.TimeoutError:
                    await msg.clear_reactions()
                    break

        except Exception as e:
            await interaction.followup.send(f"⚠️ Error listing tracked characters: `{e}`")

    # Inside run_advanced_tracker...
    elif compare:
        world_key = f"{interaction.guild_id}_{interaction.channel_id}"

        if stop:
            task = advanced_compare_tasks.pop(world_key, None)
            if task and not task.done():
                task.cancel()
                await interaction.followup.send("🛑 Compare tracking loop stopped.")
            else:
                await interaction.followup.send("⚠️ No active compare loop to stop.")
            return

        if interval is None or interval < 10:
            await interaction.followup.send("⚠️ Please provide a valid `interval` (>= 10 seconds).")
            return

        # Check if there's already a task running
        if world_key in advanced_compare_tasks and not advanced_compare_tasks[world_key].done():
            await interaction.followup.send(
                "⚠️ A compare loop is already running. Stop it first before starting a new one.")
            return

        # Store the user who started the tracking for proper notifications
        tracker_user = interaction.user

        # Keep track of which players we've already sent "active" notifications for
        # to avoid spamming the same status repeatedly
        active_character_notified = {}

        # Define check_and_compare_player_levels
        async def check_and_compare_player_levels():
            try:
                tracked_players = await get_advanced_tracked_players()
                if not tracked_players:
                    return None  # No need to notify if there are no tracked players

                results = []
                updated_lines = []
                changes_detected = False

                for line in tracked_players:
                    parts = line.strip().split(",")
                    if len(parts) < 5:
                        updated_lines.append(line if line.endswith("\n") else line + "\n")
                        continue

                    player_name = parts[0]
                    char_uuid = parts[3]

                    # Fetch online status and active character
                    profile_url = f"https://api.wynncraft.com/v3/player/{player_name}?fullResult"
                    profile_data = await fetch_json(profile_url)

                    if not profile_data or "uuid" not in profile_data:
                        updated_lines.append(line if line.endswith("\n") else line + "\n")
                        continue

                    # Check if player is actually online
                    is_online = profile_data.get("online", False)
                    world = profile_data.get("server", "Offline") if is_online else "Offline"

                    # Check if this is the active character - only valid if player is online
                    active_char_uuid = profile_data.get("activeCharacter") if is_online else None
                    is_active = is_online and active_char_uuid == char_uuid

                    # Create a unique key for this player-character combination
                    active_key = f"{player_name}_{char_uuid}"

                    # Check if we need to notify about active status
                    active_changed = False
                    if is_active and active_key not in active_character_notified:
                        # Player is now active on this character and we haven't notified yet
                        active_character_notified[active_key] = True
                        active_changed = True
                        changes_detected = True
                        results.append(
                            f"🎮 `{player_name}` is now active on their tracked character in world `{world}`!")
                    elif not is_active and active_key in active_character_notified:
                        # Player was active but isn't anymore, reset notification state
                        del active_character_notified[active_key]

                    # Fetch character data for stat tracking
                    char_url = f"https://api.wynncraft.com/v3/player/{player_name}/characters/{char_uuid}"
                    char_data = await fetch_json(char_url)

                    if not char_data or "type" not in char_data:
                        updated_lines.append(line if line.endswith("\n") else line + "\n")
                        continue

                    combat_level = int(char_data.get("level", 0)) + (char_data.get("xpPercent", 0) * 0.01)
                    professions = char_data.get("professions", {})

                    current_prof_levels = {}
                    for prof, prof_data in professions.items():
                        level = prof_data.get("level", 0)
                        xp_percent = prof_data.get("xpPercent", 0)
                        adjusted_level = level + (xp_percent * 0.01)
                        current_prof_levels[prof] = adjusted_level

                    # Parse previous levels
                    previous_combat_level = float(parts[4].split(":")[1])
                    previous_prof_levels = {
                        part.split(":")[0]: float(part.split(":")[1])
                        for part in parts[5:] if ":" in part
                    }

                    # Detect changes - using a threshold to avoid noise from tiny changes
                    combat_increase = combat_level - previous_combat_level > 0.01
                    prof_increases = {k: v for k, v in current_prof_levels.items()
                                      if v - previous_prof_levels.get(k, 0) > 0.01}

                    level_changed = combat_increase or prof_increases

                    if level_changed:
                        changes_detected = True
                        changes = []

                        if combat_increase:
                            changes.append(f"• Combat: {previous_combat_level:.2f} → {combat_level:.2f} ⬆️")

                        changed_profs = []
                        for prof, new_value in prof_increases.items():
                            old_value = previous_prof_levels.get(prof, 0)
                            changed_profs.append(f"  - {prof.capitalize()}: {old_value:.2f} → {new_value:.2f} ⬆️")

                        if changed_profs:
                            changes.append("• Increased Professions:\n" + "\n".join(changed_profs))

                        # Add world status - specifically indicate if player is online or offline
                        if is_online:
                            changes.append(f"• 🌍 World: `{world}` (Online)")

                        if is_active:
                            changes.append("• 🎮 Character is currently active!")

                        results.append(f"🔄 `{player_name}` updated stats:\n" + "\n".join(changes))

                        new_line = (
                                f"{player_name},{char_data.get('type')},{profile_data['uuid']},{char_uuid},"
                                f"combat:{combat_level:.2f}," +
                                ",".join(f"{k}:{v:.2f}" for k, v in sorted(current_prof_levels.items())) +
                                "\n"
                        )

                        updated_lines.append(new_line)
                    else:
                        # No level changes but we still want to recognize active notification changes
                        if active_changed:
                            updated_lines.append(line if line.endswith("\n") else line + "\n")
                        else:
                            updated_lines.append(line if line.endswith("\n") else line + "\n")

                # Rewrite the file with updated lines
                async with aiofiles.open(ADVANCED_TRACKER_FILE_PATH, "w") as f:
                    await f.writelines(updated_lines)

                if changes_detected:
                    return f"{tracker_user.mention}\n" + "\n\n".join(results)
                return None

            except Exception as e:
                return f"⚠️ Error during comparison: `{e}`"

        # Define start_periodic_check
        async def start_periodic_check():
            try:
                await interaction.followup.send(
                    f"🟢 Started compare loop with interval: `{interval}` seconds. Will notify when player stats increase or players become active on tracked characters.")

                while True:
                    result = await check_and_compare_player_levels()
                    if result:  # Only send messages when there are changes
                        await interaction.channel.send(result)
                    await asyncio.sleep(interval)

            except asyncio.CancelledError:
                print(f"Compare loop for {world_key} was stopped.")
                return
            except Exception as e:
                await interaction.channel.send(f"⚠️ Compare loop encountered an error and stopped: `{e}`")
                # Remove task from active tasks
                advanced_compare_tasks.pop(world_key, None)

        # Start loop and store task
        task = asyncio.create_task(start_periodic_check())
        advanced_compare_tasks[world_key] = task