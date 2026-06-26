"""Registry for background tasks that must complete on shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_background_tasks: set[asyncio.Task[Any]] = set()


def spawn_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Start a background task and register it for graceful-shutdown cleanup."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def await_background_tasks(cancel_after_s: float = 10.0) -> None:
    """Cancel background tasks; wait up to ``cancel_after_s`` s for them to finish."""
    pending = [t for t in _background_tasks if not t.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    await asyncio.wait(pending, timeout=cancel_after_s)
