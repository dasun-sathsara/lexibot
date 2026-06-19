"""Data access for idempotency, user settings, and audit."""

from __future__ import annotations

from sqlalchemy import select
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from vocab_bot.db.tables import AuditLog, ProcessedItem, UserSettings


class ProcessedItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, job_id: str) -> ProcessedItem | None:
        return await self._session.get(ProcessedItem, job_id)

    async def record(
        self, *, job_id: str, user_id: int, word_field: str, outcome: str
    ) -> ProcessedItem:
        """Insert or update the processed-item record (last-outcome wins)."""
        existing = await self._session.get(ProcessedItem, job_id)
        if existing is not None:
            existing.outcome = outcome
            existing.word_field = word_field
            self._session.add(existing)
            return existing
        item = ProcessedItem(job_id=job_id, user_id=user_id, word_field=word_field, outcome=outcome)
        self._session.add(item)
        return item


class UserSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> UserSettings | None:
        return await self._session.get(UserSettings, user_id)

    async def upsert(
        self, user_id: int, *, gemini_model: str | None = None, voice_gender: str | None = None
    ) -> UserSettings:
        row = await self._session.get(UserSettings, user_id)
        if row is None:
            row = UserSettings(user_id=user_id)
        if gemini_model is not None:
            row.gemini_model = gemini_model
        if voice_gender is not None:
            row.voice_gender = voice_gender
        self._session.add(row)
        return row


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, user_id: int, event: str, detail: str = "") -> None:
        self._session.add(AuditLog(user_id=user_id, event=event, detail=detail))

    async def recent(self, limit: int = 50) -> list[AuditLog]:
        result = await self._session.execute(
            select(AuditLog).order_by(col(AuditLog.created_at).desc()).limit(limit)
        )
        return list(result.scalars().all())
