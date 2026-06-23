"""AnkiConnect client over httpx.

AnkiConnect exposes a single JSON-RPC endpoint; every action is a POST of
``{"action", "version", "params"}`` and the reply is ``{"result", "error"}``.

The :func:`build_find_query` and :func:`escape_query_term` helpers are pure functions so
the search-string hardening (UPSERT-04) is unit-testable without any HTTP mock.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lexibot.core.exceptions import AnkiError, AnkiUnavailable

ANKICONNECT_VERSION = 6

# Default retry policy for transient AnkiConnect failures (RETRY-03/05): bounded attempts +
# capped exponential backoff. Connection refused -> AnkiUnavailable, which is NOT retried
# here (the worker handles offline re-queueing instead).
_DEFAULT_MAX_ATTEMPTS = 4


def escape_query_term(term: str) -> str:
    r"""Escape a value for use *inside* a double-quoted Anki search term.

    Anki search syntax wraps a term in double quotes; an embedded ``"`` would otherwise
    terminate the term early (query injection / malformed search). Backslashes are escaped
    first, then double quotes (UPSERT-04). Example: ``say "hi"`` -> ``say \"hi\"``.
    """
    return term.replace("\\", "\\\\").replace('"', '\\"')


def build_find_query(note_type: str, word_field: str) -> str:
    r"""Build the collection-wide ``findNotes`` query for an exact ``Word`` match.

    Intentionally has **no** ``deck:`` constraint so the match is collection-wide
    (UPSERT-08). Both the note-type and the word value are quote-escaped (UPSERT-04).
    """
    nt = escape_query_term(note_type)
    wf = escape_query_term(word_field)
    return f'"note:{nt}" "Word:{wf}"'


class AnkiConnectError(AnkiError):
    """AnkiConnect returned a non-null ``error`` field."""


class AnkiConnect:
    """Concrete :class:`~lexibot.anki.ports.AnkiConnectClient` over httpx."""

    def __init__(
        self, base_url: str, client: httpx.AsyncClient, *, max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    ) -> None:
        self._url = base_url
        self._client = client
        self._max_attempts = max_attempts

    async def _invoke(self, action: str, **params: Any) -> Any:
        payload = {"action": action, "version": ANKICONNECT_VERSION, "params": params}

        async def _once() -> Any:
            try:
                response = await self._client.post(self._url, json=payload)
                response.raise_for_status()
            except httpx.ConnectError as exc:
                raise AnkiUnavailable(f"AnkiConnect unreachable at {self._url}") from exc
            except httpx.HTTPStatusError as exc:
                # 5xx is transient and worth retrying; treat as AnkiConnectError.
                raise AnkiConnectError(f"AnkiConnect HTTP {exc.response.status_code}") from exc
            data = response.json()
            if data.get("error") is not None:
                raise AnkiConnectError(str(data["error"]))
            return data.get("result")

        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(AnkiConnectError),
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.5, max=8),
            reraise=True,
        ):
            with attempt:
                return await _once()
        raise AnkiConnectError("AnkiConnect retry exhausted")  # pragma: no cover

    async def find_notes(self, query: str) -> list[int]:
        result = await self._invoke("findNotes", query=query)
        return list(result or [])

    async def add_note(
        self,
        *,
        deck: str,
        note_type: str,
        fields: dict[str, str],
        tags: list[str],
        allow_duplicate: bool,
    ) -> int:
        note = {
            "deckName": deck,
            "modelName": note_type,
            "fields": fields,
            "tags": tags,
            "options": {"allowDuplicate": allow_duplicate},
        }
        result = await self._invoke("addNote", note=note)
        return int(result)

    async def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        await self._invoke("updateNoteFields", note={"id": note_id, "fields": fields})

    async def update_note_tags(self, note_id: int, tags: list[str]) -> None:
        await self._invoke("updateNoteTags", note=note_id, tags=tags)

    async def store_media_file(self, filename: str, data_b64: str) -> None:
        await self._invoke("storeMediaFile", filename=filename, data=data_b64)

    async def delete_media_file(self, filename: str) -> None:
        await self._invoke("deleteMediaFile", filename=filename)

    async def delete_notes(self, note_ids: list[int]) -> None:
        await self._invoke("deleteNotes", notes=note_ids)

    async def sync(self) -> None:
        await self._invoke("sync")


def encode_media(data: bytes) -> str:
    """Base64-encode media bytes for ``storeMediaFile``."""
    return base64.b64encode(data).decode("ascii")
