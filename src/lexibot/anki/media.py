"""Media storage for a card's audio clips.

Filenames are produced by :func:`lexibot.core.models.media_filename` (the ``tgb_`` namespace
with a text+voice hash). On both the add and rewrite paths we store the same three
filenames, so a rewrite deterministically *replaces* that word's media (UPSERT-05).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lexibot.anki.connect import encode_media

if TYPE_CHECKING:
    from lexibot.anki.ports import AnkiConnectClient
    from lexibot.core.models import Card


class MediaStore:
    """Stores a card's media clips via ``storeMediaFile``."""

    def __init__(self, client: AnkiConnectClient) -> None:
        self._client = client

    async def store(self, card: Card) -> None:
        """Upload each of the card's clips. A no-op when the card has no media."""
        for clip in card.media:
            await self._client.store_media_file(clip.filename, encode_media(clip.audio))
