# fetch.py
from typing import Any

from ratelimit import limits, sleep_and_retry
import time
from requests import get, RequestException

@sleep_and_retry
@limits(calls=95, period=60)
def fetch_json(url: str) -> dict[Any, Any] | None | Any:
    while True:
        try:
            response = get(url, timeout=10)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            print(f"[ERROR] Fetch failed: {e}")
            return {}
