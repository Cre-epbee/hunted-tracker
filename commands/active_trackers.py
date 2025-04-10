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
import importlib

from shared_state import tracker_task, detect_world_tasks

async def run_active_trackers(
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