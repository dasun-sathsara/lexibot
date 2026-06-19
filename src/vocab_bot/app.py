"""FastAPI app: Telegram webhook route + lifespan wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Header, Request, Response

from vocab_bot.bot.dispatcher import build_dispatcher
from vocab_bot.config import Settings, get_settings
from vocab_bot.container import create_redis_pool
from vocab_bot.logging import configure_logging

log = structlog.get_logger(__name__)

WEBHOOK_PATH = "/webhook"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level)

    bot = Bot(token=settings.telegram_token.get_secret_value())
    arq = await create_redis_pool(settings)
    dp = build_dispatcher(allowed_ids=settings.allowed_ids, arq=arq)

    app.state.bot = bot
    app.state.dp = dp
    app.state.settings = settings

    if settings.webhook_base_url:
        secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
        await bot.set_webhook(
            f"{settings.webhook_base_url.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=secret,
            drop_pending_updates=True,
        )
        log.info("webhook.set", url=settings.webhook_base_url)
    try:
        yield
    finally:
        await bot.session.close()
        await arq.aclose()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(WEBHOOK_PATH)
    async def webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> Response:
        settings: Settings = request.app.state.settings
        if settings.webhook_secret is not None:
            expected = settings.webhook_secret.get_secret_value()
            if x_telegram_bot_api_secret_token != expected:
                return Response(status_code=403)
        bot: Bot = request.app.state.bot
        dp: Dispatcher = request.app.state.dp
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
        return Response(status_code=200)

    return app
