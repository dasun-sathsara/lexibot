"""Typed, validated, secret-aware settings.

All env vars are prefixed ``VB_``; secrets are :class:`~pydantic.SecretStr`; list-valued
vars parse from comma-separated strings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VB_", extra="ignore")

    # Telegram
    telegram_token: SecretStr
    allowed_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    webhook_secret: SecretStr | None = None
    webhook_base_url: str | None = None
    admin_id: int | None = None

    # Gemini
    gemini_api_keys: Annotated[list[SecretStr], NoDecode]
    gemini_model: str = "gemini-3.5-flash"
    gemini_cooldown_s: float = 60.0

    # Azure MAI-Voice-2
    azure_speech_key: SecretStr
    azure_speech_endpoint: str
    voice_gender: Literal["female", "male"] = "female"

    # Anki
    ankiconnect_url: str = "http://anki-headless:8765"
    target_deck: str = "Daily"
    note_type: str = "Eng Vocab 2 Examples"

    # Infra
    redis_dsn: str = "redis://redis:6379/0"
    database_url: str = "sqlite+aiosqlite:///data/vocab.db"

    # Observability / misc
    tz: str = "Asia/Colombo"
    log_level: str = "INFO"

    @field_validator("allowed_ids", mode="before")
    @classmethod
    def _split_ids(cls, v: object) -> object:
        """Parse ``VB_ALLOWED_IDS="111,222"`` into ``[111, 222]`` (CONF-02)."""
        if isinstance(v, str):
            return [int(p.strip()) for p in v.split(",") if p.strip()]
        return v

    @field_validator("gemini_api_keys", mode="before")
    @classmethod
    def _split_keys(cls, v: object) -> object:
        """Parse ``VB_GEMINI_API_KEYS="k1,k2,k3"`` into 3 secrets (CONF-01)."""
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def gemini_keys_plain(self) -> list[str]:
        """The raw key strings for the key pool (never logged)."""
        return [k.get_secret_value() for k in self.gemini_api_keys]


@lru_cache
def get_settings() -> Settings:
    return Settings()
