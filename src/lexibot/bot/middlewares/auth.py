"""Whitelist middleware.

Drops any update whose sender id is not in ``allowed_ids`` before any handler runs
(AUTH-01/02). The drop is silent: no reply, no handler invocation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, allowed_ids: list[int]) -> None:
        self._allowed = set(allowed_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None and isinstance(event, Message | CallbackQuery):
            user = event.from_user
        if user is None or user.id not in self._allowed:
            return None  # silently drop
        return await handler(event, data)
