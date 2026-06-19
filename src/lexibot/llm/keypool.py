"""Gemini API-key pool.

Round-robin selection with per-key cooldown. On an HTTP 429 the offending key is
penalized and skipped until its cooldown expires; concurrency scales with the number of
keys. A single lock serializes selection so concurrent acquires never hand the same slot
to two callers.
"""

from __future__ import annotations

import asyncio
import itertools
import time


class GeminiKeyPool:
    def __init__(self, keys: list[str], cooldown_s: float = 60.0) -> None:
        if not keys:
            raise ValueError("at least one Gemini key required")
        self._keys = list(keys)
        self._ring = itertools.cycle(self._keys)
        self._until: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._cooldown_s = cooldown_s

    async def acquire(self) -> str:
        """Return the next available key, waiting out cooldowns if every key is cooling."""
        while True:
            async with self._lock:
                now = time.monotonic()
                for _ in range(len(self._keys)):
                    key = next(self._ring)
                    if self._until.get(key, 0.0) <= now:
                        return key
                # Every key is cooling; compute how long until the soonest is free.
                wait = max(0.0, min(self._until.values()) - now)
            await asyncio.sleep(wait)

    def penalize(self, key: str) -> None:
        """Put ``key`` into cooldown (called on HTTP 429)."""
        self._until[key] = time.monotonic() + self._cooldown_s
