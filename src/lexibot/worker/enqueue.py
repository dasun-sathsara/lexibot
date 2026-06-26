"""Chunking, soft-cap, dedup, and deterministic job ids.

The job id coalesces rapid resends: the runner uses it as the key into its in-flight
batch registry, so a second submission while the first is running is a no-op. The
Anki upsert is the final backstop.
"""

from __future__ import annotations

from lexibot.core.models import RawItem

DEFAULT_CHUNK_SIZE = 10
SOFT_CAP = 50


def normalize_word_key(headword: str) -> str:
    """Case-fold + trim the raw headword for the job-id key (IDEM-05)."""
    return headword.strip().casefold()


def job_id(user_id: int, headword: str) -> str:
    """Deterministic job id: ``w:<user_id>:<normalized_word>`` (used as the runner key)."""
    return f"w:{user_id}:{normalize_word_key(headword)}"


def chunk_items(items: list[RawItem], *, size: int = DEFAULT_CHUNK_SIZE) -> list[list[RawItem]]:
    """Split items into chunks of ``size`` (order preserved, no empty trailing chunk)."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def apply_soft_cap(
    items: list[RawItem], *, cap: int = SOFT_CAP
) -> tuple[list[RawItem], list[RawItem]]:
    """Return ``(kept, dropped)`` where at most ``cap`` items are kept (CHUNK-04)."""
    return items[:cap], items[cap:]


def dedupe_items(items: list[RawItem], *, user_id: int) -> list[RawItem]:
    """Drop later duplicates that map to the same job id within one batch (CHUNK-05)."""
    seen: set[str] = set()
    out: list[RawItem] = []
    for item in items:
        key = job_id(user_id, item.headword)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
