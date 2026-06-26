"""Anki upsert gateway: find -> update | add.

Match is collection-wide by exact ``Word`` field value. Media is always stored first;
on a hit we rewrite the first matching note in place, otherwise we add a new note
with ``allowDuplicate``.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo

from lexibot.anki.connect import build_find_query
from lexibot.anki.media import MediaStore
from lexibot.anki.ports import AnkiConnectClient
from lexibot.core.enums import ItemOutcome
from lexibot.core.models import Card

BOT_TAG = "tgbot"


def date_tag(now: datetime, tz: str) -> str:
    """The ``added::YYYY-MM-DD`` tag for ``now`` in the given ``tz`` timezone."""
    local = now.astimezone(ZoneInfo(tz))
    return f"added::{local:%Y-%m-%d}"


class AnkiUpsertGateway:
    """Concrete :class:`~lexibot.anki.ports.AnkiGateway`."""

    def __init__(
        self,
        client: AnkiConnectClient,
        *,
        deck: str,
        note_type: str,
        tz: str = "Asia/Colombo",
    ) -> None:
        self._client = client
        self._media = MediaStore(client)
        self._deck = deck
        self._note_type = note_type
        self._tz = tz

    def _tags(self, now: datetime | None = None) -> list[str]:
        return [BOT_TAG, date_tag(now or datetime.now(tz=ZoneInfo(self._tz)), self._tz)]

    async def upsert(self, card: Card) -> ItemOutcome:
        query = build_find_query(self._note_type, card.word_field)
        note_ids = await self._client.find_notes(query)
        tags = self._tags()

        # Always store media first. If a subsequent note operation fails we are left with
        # orphaned media rather than a note pointing at missing files.
        await self._media.store(card)

        if note_ids:
            note_id = note_ids[0]
            await self._client.update_note_fields(note_id, card.fields)
            await self._client.update_note_tags(note_id, tags)
            return ItemOutcome.REWRITTEN

        try:
            await self._client.add_note(
                deck=self._deck,
                note_type=self._note_type,
                fields=card.fields,
                tags=tags,
                allow_duplicate=True,
            )
        except Exception:
            # Best-effort cleanup so failed adds do not leave orphaned media behind.
            with contextlib.suppress(Exception):
                await self._media.delete(card)
            raise
        return ItemOutcome.ADDED

    async def sync(self) -> None:
        await self._client.sync()
