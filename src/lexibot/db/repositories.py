"""Data access for idempotency, user settings, and audit."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from lexibot.db.engine import session_scope
from lexibot.db.tables import AuditLog, ProcessedItem, UserSettings


async def get_user_model(engine: AsyncEngine, user_id: int) -> str | None:
    """Return the user's preferred Gemini model, if any."""
    async with session_scope(engine) as session:
        repo = UserSettingsRepository(session)
        row = await repo.get(user_id)
        return row.gemini_model if row else None


async def set_user_model(engine: AsyncEngine, user_id: int, model: str) -> None:
    """Persist the user's preferred Gemini model."""
    async with session_scope(engine) as session:
        repo = UserSettingsRepository(session)
        await repo.upsert(user_id, gemini_model=model)


async def record_processed_item(
    engine: AsyncEngine,
    *,
    job_id: str,
    user_id: int,
    word_field: str,
    outcome: str,
) -> None:
    """Upsert the last-known outcome for a processed item."""
    async with session_scope(engine) as session:
        repo = ProcessedItemRepository(session)
        await repo.record(job_id=job_id, user_id=user_id, word_field=word_field, outcome=outcome)


async def add_audit_event(
    engine: AsyncEngine, *, user_id: int, event: str, detail: str = ""
) -> None:
    """Append an audit log entry."""
    async with session_scope(engine) as session:
        repo = AuditRepository(session)
        await repo.add(user_id=user_id, event=event, detail=detail)


class ProcessedItemRepository:
    """Manages processed-item idempotency records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, job_id: str) -> ProcessedItem | None:
        """Look up a processed item by its job id."""
        return await self._session.get(ProcessedItem, job_id)

    async def record(
        self, *, job_id: str, user_id: int, word_field: str, outcome: str
    ) -> ProcessedItem:
        """Insert or update the processed-item record — last outcome and word_field values win."""
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
    """Per-user model/voice preferences repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> UserSettings | None:
        """Look up user settings by user id."""
        return await self._session.get(UserSettings, user_id)

    async def upsert(
        self, user_id: int, *, gemini_model: str | None = None, voice_gender: str | None = None
    ) -> UserSettings:
        """Create or update user settings; only sets non-``None`` fields."""
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
    """Append-only audit trail repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, user_id: int, event: str, detail: str = "") -> None:
        """Append an audit log entry."""
        self._session.add(AuditLog(user_id=user_id, event=event, detail=detail))

    async def recent(self, limit: int = 50) -> list[AuditLog]:
        """Return the most recent audit log entries, newest first."""
        result = await self._session.execute(
            select(AuditLog).order_by(col(AuditLog.created_at).desc()).limit(limit)
        )
        return list(result.scalars().all())
