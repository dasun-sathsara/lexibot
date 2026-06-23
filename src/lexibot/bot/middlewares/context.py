"""Request-scoped structlog context binding."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class LoggingContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=str(uuid4()))
        user = data.get("event_from_user")
        if user is not None:
            structlog.contextvars.bind_contextvars(user_id=user.id)
        if isinstance(event, Message):
            structlog.contextvars.bind_contextvars(update="message")
        elif isinstance(event, CallbackQuery):
            structlog.contextvars.bind_contextvars(update="callback")
        try:
            return await handler(event, data)
        finally:
            structlog.contextvars.clear_contextvars()
