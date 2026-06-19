"""ARQ worker settings (architecture §4, §10).

Builds the shared adapter graph once at worker startup (``on_startup``) and stores it on the
ARQ context so tasks can reach the pipeline/LLM. Job retries + bounded backoff give the
resilience the test-spec describes (RETRY-04/05).
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from vocab_bot.config import get_settings
from vocab_bot.container import build_worker_context, close_worker_context
from vocab_bot.logging import configure_logging
from vocab_bot.worker.tasks import process_chunk


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx.update(await build_worker_context(settings))


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_worker_context(ctx)


class WorkerSettings:
    """ARQ entrypoint: ``arq vocab_bot.worker.settings.WorkerSettings``."""

    functions: ClassVar[list[Any]] = [process_chunk]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 5
    job_timeout = 300

    @staticmethod
    def redis_settings() -> RedisSettings:
        return RedisSettings.from_dsn(get_settings().redis_dsn)
