"""Admin alerting on repeated failures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from aiogram import Bot

log = structlog.get_logger(__name__)


class AdminAlerter:
    """DMs the admin Telegram id when an item exhausts retries."""

    def __init__(self, bot: Bot, admin_id: int | None) -> None:
        self._bot = bot
        self._admin_id = admin_id

    async def alert(self, message: str) -> None:
        log.error("admin.alert", message=message)
        if self._admin_id is None:
            return
        try:
            await self._bot.send_message(self._admin_id, f"\u26a0\ufe0f {message}")
        except Exception:  # pragma: no cover - best-effort notification
            log.warning("admin.alert.failed", message=message)
