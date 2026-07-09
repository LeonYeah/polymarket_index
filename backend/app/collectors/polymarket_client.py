from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import httpx


class PolymarketHttpClient:
    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def get_json(
        self, path: str, params: Mapping[str, Any] | None = None
    ) -> tuple[dict[str, Any] | list[Any] | str, int, int]:
        started = time.perf_counter()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.get(path, params=params)
            duration_ms = int((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            return response.json(), response.status_code, duration_ms

