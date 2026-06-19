"""aiogram Dispatcher assembly + router registration (architecture §2)."""

from __future__ import annotations

from aiogram import Dispatcher
from arq.connections import ArqRedis

from vocab_bot.bot.handlers import callbacks, commands, words
from vocab_bot.bot.middlewares.auth import WhitelistMiddleware
from vocab_bot.bot.middlewares.context import LoggingContextMiddleware


def build_dispatcher(*, allowed_ids: list[int], arq: ArqRedis) -> Dispatcher:
    dp = Dispatcher()

    # Outer middlewares run before filtering, so auth drops disallowed updates early.
    logging_mw = LoggingContextMiddleware()
    auth_mw = WhitelistMiddleware(allowed_ids)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(logging_mw)
        observer.outer_middleware(auth_mw)

    # Inject the ARQ pool into every handler via workflow data.
    dp["arq"] = arq

    # Order matters: commands and callbacks before the catch-all word ingester.
    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(words.router)
    return dp
