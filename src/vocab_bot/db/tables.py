"""SQLModel tables (architecture §9)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProcessedItem(SQLModel, table=True):
    """Idempotency key + last outcome for a processed word."""

    job_id: str = Field(primary_key=True)  # w:<user>:<normalized_word>
    user_id: int = Field(index=True)
    word_field: str = Field(index=True)
    outcome: str
    created_at: datetime = Field(default_factory=_utcnow)


class UserSettings(SQLModel, table=True):
    """Per-user model/voice preferences."""

    user_id: int = Field(primary_key=True)
    gemini_model: str | None = None
    voice_gender: str | None = None


class AuditLog(SQLModel, table=True):
    """Append-only audit trail of significant events."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    event: str
    detail: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
