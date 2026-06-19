"""ARQ worker settings.

Builds the shared adapter graph once at worker startup (``on_startup``) and stores it on the
ARQ context so tasks can reach the pipeline/LLM. Job retries + bounded backoff give the
resilience the test-spec describes (RETRY-04/05).
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from lexibot.config import get_settings
from lexibot.container import build_worker_context, close_worker_context
from lexibot.logging import configure_logging
from lexibot.worker.tasks import process_chunk


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx.update(await build_worker_context(settings))


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_worker_context(ctx)


class WorkerSettings:
    """ARQ entrypoint: ``arq lexibot.worker.settings.WorkerSettings``."""

    functions: ClassVar[list[Any]] = [process_chunk]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 5
    job_timeout = 300

    try:
        redis_settings = RedisSettings.from_dsn(get_settings().redis_dsn)
    except Exception:
        redis_settings = RedisSettings()
