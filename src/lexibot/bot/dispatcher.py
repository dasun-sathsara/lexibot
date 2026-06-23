"""aiogram Dispatcher assembly + router registration."""

from __future__ import annotations

from aiogram import Dispatcher
from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncEngine

from lexibot.bot.handlers import callbacks, commands, words
from lexibot.bot.middlewares.auth import WhitelistMiddleware
from lexibot.bot.middlewares.context import LoggingContextMiddleware


def build_dispatcher(
    *, allowed_ids: list[int], arq: ArqRedis, engine: AsyncEngine | None = None
) -> Dispatcher:
    dp = Dispatcher()

    # Outer middlewares run before filtering, so auth drops disallowed updates early.
    logging_mw = LoggingContextMiddleware()
    auth_mw = WhitelistMiddleware(allowed_ids)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(logging_mw)
        observer.outer_middleware(auth_mw)

    # Inject the ARQ pool and DB engine into every handler via workflow data.
    dp["arq"] = arq
    if engine is not None:
        dp["engine"] = engine

    # Order matters: commands and callbacks before the catch-all word ingester.
    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(words.router)
    return dp
