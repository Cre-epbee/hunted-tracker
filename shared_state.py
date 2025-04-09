from typing import Optional
import asyncio

# Shared variables
tracker_task: Optional[asyncio.Task] = None
detect_world_tasks: dict[str, asyncio.Task] = {}