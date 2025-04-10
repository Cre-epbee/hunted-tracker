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
        combat_level, char_class, prof_levels =  get_detail_character_data(add,char_uuid)

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
                # Make a dict of profs like {"combat": 105, "fishing": 110, ...}
                profs = dict(item.split(":") for item in parts[3:] if ":" in item)

                # Convert the profession levels to integers, and default to 0 if the value is not present
                fishing = float(profs.get("fishing", 0))
                mining = float(profs.get("mining", 0))
                woodcutting = float(profs.get("woodcutting", 0))
                farming = float(profs.get("farming", 0))

                # Calculate the average of these four professions
                avg = (fishing + mining + woodcutting + farming) / 4

                row = {
                    "Player": player,
                    "Class": character_class,
                    "Combat": profs.get("combat", "N/A"),
                    "Fishing": fishing,
                    "Mining": mining,
                    "Woodcutting": woodcutting,
                    "Farming": farming,
                    "Prof Average": f"{avg:.2f}"  # Display the average rounded to two decimal places
                }

                all_rows.append(row)

            # Format into a text table
            col_headers = ["Player","Class", "Combat", "Fishing", "Mining", "Woodcutting", "Farming", "Prof Average"]
            col_widths = {col: max(len(col), max(len(str(row[col])) for row in all_rows)) for col in col_headers}

            header_line = " | ".join(col.ljust(col_widths[col]) for col in col_headers)
            separator = "-+-".join("-" * col_widths[col] for col in col_headers)
            data_lines = [" | ".join(str(row[col]).ljust(col_widths[col]) for col in col_headers) for row in all_rows]

            table = "\n".join([header_line, separator] + data_lines)
            await interaction.followup.send(f"```text\n{table}\n```")

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

        async def start_periodic_check():
            try:
                while True:
                    await check_and_compare_player_levels()
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                print(f"Compare loop for {world_key} was stopped.")

        async def check_and_compare_player_levels():
            try:
                tracked_players = await get_advanced_tracked_players()
                if not tracked_players:
                    return

                results = []
                updated_lines = []

                for line in tracked_players:
                    parts = line.strip().split(",")
                    if len(parts) < 5:
                        continue

                    player_name = parts[0]
                    char_uuid = parts[3]

                    #Fetch online status
                    profile_url = f"https://api.wynncraft.com/v3/player/{player_name}?fullResult"
                    profile_data = await fetch_json(profile_url)

                    if not profile_data or "uuid" not in profile_data:
                        continue

                    world = profile_data.get("server", "Offline")

                    # Fetch character data
                    char_url = f"https://api.wynncraft.com/v3/player/{player_name}/characters/{char_uuid}"
                    char_data = await fetch_json(char_url)

                    if not char_data or "type" not in char_data:
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

                    # Detect changes
                    combat_diff = combat_level != previous_combat_level
                    prof_diff = any(
                        current_prof_levels.get(k, 0) != previous_prof_levels.get(k, 0)
                        for k in current_prof_levels
                    )

                    if combat_diff or prof_diff:
                        changes = []

                        if combat_diff:
                            changes.append(f"• Combat: {previous_combat_level:.2f} → {combat_level:.2f}")

                        changed_profs = []
                        for prof, new_value in current_prof_levels.items():
                            old_value = previous_prof_levels.get(prof)
                            if old_value is not None and abs(new_value - old_value) > 0.01:
                                changed_profs.append(f"  - {prof.capitalize()}: {old_value:.2f} → {new_value:.2f}")

                        if changed_profs:
                            changes.append("• Changed Professions:\n" + "\n".join(changed_profs))

                        changes.append(f"• 🌍 World: `{world}`")

                        results.append(f"{interaction.user.mention}\n"
                                       f"🔄`{player_name}` updated stats:\n" + "\n".join(changes))

                        new_line = (
                                f"{player_name},{char_data.get('type')},{profile_data['uuid']},{char_uuid},"
                                f"combat:{combat_level:.2f}," +
                                ",".join(f"{k}:{v:.2f}" for k, v in sorted(current_prof_levels.items())) +
                                "\n"  
                        )

                        updated_lines.append(new_line)
                    else:
                        updated_lines.append(line if line.endswith("\n") else line + "\n")

                # Rewrite the file with updated lines
                async with aiofiles.open(ADVANCED_TRACKER_FILE_PATH, "w") as f:
                    await f.writelines(updated_lines)

                if results:
                    await interaction.followup.send("\n".join(results))
                else:
                    await interaction.followup.send("✅ No changes detected.")

            except Exception as e:
                await interaction.followup.send(f"⚠️ Error during comparison: `{e}`")

        # Start loop and store task
        task = asyncio.create_task(start_periodic_check())
        advanced_compare_tasks[world_key] = task
        await interaction.followup.send(f"🟢 Started compare loop. Interval: `{interval}` seconds.")


