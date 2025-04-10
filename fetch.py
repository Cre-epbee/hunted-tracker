# fetch.py
from typing import Any
import asyncio
import aiohttp

RATE_LIMIT_CALLS = 95
RATE_LIMIT_PERIOD = 60

semaphore = asyncio.Semaphore(RATE_LIMIT_CALLS)

async def fetch_json(url: str) -> dict[Any, Any] | None:
    async with semaphore:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 5))
                        print(f"[429] Retrying after {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        return await fetch_json(url)  # Retry
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                print(f"[ERROR] Fetch failed: {e}")
                return {}
