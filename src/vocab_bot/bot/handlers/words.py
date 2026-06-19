"""Free-text word ingestion.

Parses the message, applies the soft cap and dedup, chunks the items, and enqueues one
``process_chunk`` job per chunk with a deterministic id so rapid resends coalesce. A single
status message is posted and later edited in place with the batch summary.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message
from arq.connections import ArqRedis

from vocab_bot.core.parsing import parse_message
from vocab_bot.worker.enqueue import (
    DEFAULT_CHUNK_SIZE,
    apply_soft_cap,
    chunk_items,
    dedupe_items,
    job_id,
)

router = Router(name="words")


@router.message()
async def ingest_words(message: Message, arq: ArqRedis) -> None:
    user = message.from_user
    if user is None:
        return
    items = parse_message(message.text or "")
    if not items:
        await message.answer("Send me a word or a list of words.")
        return

    items = dedupe_items(items, user_id=user.id)
    kept, dropped = apply_soft_cap(items)

    note = ""
    if dropped:
        note = f"\n\u26a0\ufe0f Only the first {len(kept)} of {len(kept) + len(dropped)} processed."

    status = await message.answer(f"\u23f3 Queued {len(kept)} word(s)\u2026{note}")

    for chunk in chunk_items(kept, size=DEFAULT_CHUNK_SIZE):
        await arq.enqueue_job(
            "process_chunk",
            [item.model_dump() for item in chunk],
            user.id,
            _job_id=job_id(user.id, "+".join(i.headword for i in chunk)),
        )

    # The worker edits `status` in place as chunks drain; store its id for the worker.
    _ = status
