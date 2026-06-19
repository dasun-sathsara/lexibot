"""LLM port (Protocol)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from vocab_bot.core.models import RawItem, Sense


@runtime_checkable
class LanguageModel(Protocol):
    async def enrich(
        self, items: list[RawItem], *, sense_hint: str | None = None
    ) -> list[Sense]: ...
