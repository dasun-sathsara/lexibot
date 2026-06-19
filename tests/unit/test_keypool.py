"""KEY-01 .. KEY-07 — Gemini key pool.

Timing is controlled by the ``clock`` fixture (monkeypatched ``time.monotonic``) and a
patched ``asyncio.sleep`` that advances the fake clock instead of really waiting.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from vocab_bot.llm.keypool import GeminiKeyPool


@pytest.fixture
def advancing_sleep(monkeypatch: pytest.MonkeyPatch, clock: dict[str, float]) -> Callable[[], None]:
    """Patch ``asyncio.sleep`` so awaiting it advances the fake monotonic clock."""

    async def _sleep(delay: float, *args: object, **kwargs: object) -> None:
        clock["now"] += delay

    monkeypatch.setattr("vocab_bot.llm.keypool.asyncio.sleep", _sleep)
    return lambda: None


async def test_key_01_round_robin(clock: dict[str, float]) -> None:
    pool = GeminiKeyPool(["k1", "k2", "k3"], cooldown_s=60)
    got = [await pool.acquire() for _ in range(5)]
    assert got == ["k1", "k2", "k3", "k1", "k2"]


async def test_key_02_penalized_key_skipped(clock: dict[str, float]) -> None:
    pool = GeminiKeyPool(["k1", "k2", "k3"], cooldown_s=60)
    pool.penalize("k2")
    got = [await pool.acquire() for _ in range(3)]
    assert got == ["k1", "k3", "k1"]


async def test_key_03_all_penalized_waits_for_soonest(
    clock: dict[str, float], advancing_sleep: Callable[[], None]
) -> None:
    pool = GeminiKeyPool(["k1", "k2", "k3"], cooldown_s=60)
    pool.penalize("k1")
    clock["now"] += 10  # k2 penalized 10s later -> k1 cools down soonest
    pool.penalize("k2")
    clock["now"] += 10
    pool.penalize("k3")
    # All cooling; acquire must wait until the soonest (k1) expires, then return it.
    got = await pool.acquire()
    assert got == "k1"
    assert clock["now"] >= 1060.0


async def test_key_04_cooldown_boundary_inclusive(clock: dict[str, float]) -> None:
    pool = GeminiKeyPool(["k1", "k2"], cooldown_s=60)
    pool.penalize("k1")  # until = 1060
    # Advance to exactly the expiry instant; key must be reusable (uses <=).
    clock["now"] = 1060.0
    got = [await pool.acquire() for _ in range(2)]
    assert "k1" in got


async def test_key_05_single_key_penalized_waits(
    clock: dict[str, float], advancing_sleep: Callable[[], None]
) -> None:
    pool = GeminiKeyPool(["only"], cooldown_s=30)
    pool.penalize("only")
    got = await pool.acquire()  # must not infinite-loop
    assert got == "only"
    assert clock["now"] >= 1030.0


def test_key_06_empty_raises() -> None:
    with pytest.raises(ValueError):
        GeminiKeyPool([])


async def test_key_07_concurrent_acquires_no_race(clock: dict[str, float]) -> None:
    pool = GeminiKeyPool(["k1", "k2", "k3"], cooldown_s=60)
    results = await asyncio.gather(*(pool.acquire() for _ in range(9)))
    # Each key handed out exactly 3 times (round-robin, lock prevents double-hand-out).
    assert sorted(results) == ["k1", "k1", "k1", "k2", "k2", "k2", "k3", "k3", "k3"]
