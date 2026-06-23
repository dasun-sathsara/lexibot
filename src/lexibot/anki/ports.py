"""Anki ports (Protocols).

``AnkiConnectClient`` is the thin RPC surface (one method per AnkiConnect action) that the
httpx adapter implements. ``AnkiGateway`` is the higher-level port the pipeline depends on;
its concrete implementation is built on top of an ``AnkiConnectClient``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from lexibot.core.enums import ItemOutcome
    from lexibot.core.models import Card


@runtime_checkable
class AnkiConnectClient(Protocol):
    """Low-level AnkiConnect RPC actions used by the gateway."""

    async def find_notes(self, query: str) -> list[int]: ...

    async def add_note(
        self,
        *,
        deck: str,
        note_type: str,
        fields: dict[str, str],
        tags: list[str],
        allow_duplicate: bool,
    ) -> int: ...

    async def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None: ...

    async def update_note_tags(self, note_id: int, tags: list[str]) -> None: ...

    async def store_media_file(self, filename: str, data_b64: str) -> None: ...

    async def delete_media_file(self, filename: str) -> None: ...

    async def delete_notes(self, note_ids: list[int]) -> None: ...

    async def sync(self) -> None: ...


@runtime_checkable
class AnkiGateway(Protocol):
    """Higher-level Anki write path used by the pipeline."""

    async def upsert(self, card: Card) -> ItemOutcome: ...

    async def sync(self) -> None: ...
