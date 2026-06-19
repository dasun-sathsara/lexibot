"""CHUNK-01..05 and IDEM-01/02/05 — chunking + job-id determinism.

Only the pure-logic cases are covered here. IDEM-03 (coalescing while pending) and IDEM-04
(duplicate job race -> upsert backstop) require a live ARQ/Redis + Anki and are out of scope.
"""

from __future__ import annotations

from vocab_bot.core.models import RawItem
from vocab_bot.worker.enqueue import (
    DEFAULT_CHUNK_SIZE,
    SOFT_CAP,
    apply_soft_cap,
    chunk_items,
    dedupe_items,
    job_id,
    normalize_word_key,
)


def _items(words: list[str]) -> list[RawItem]:
    return [RawItem(headword=w) for w in words]


# --- CHUNK ---------------------------------------------------------------


def test_chunk_01_25_items_into_10s() -> None:
    chunks = chunk_items(_items([f"w{i}" for i in range(25)]), size=10)
    assert [len(c) for c in chunks] == [10, 10, 5]
    # Order preserved.
    flat = [it.headword for c in chunks for it in c]
    assert flat == [f"w{i}" for i in range(25)]


def test_chunk_02_exactly_10() -> None:
    chunks = chunk_items(_items([f"w{i}" for i in range(10)]), size=10)
    assert [len(c) for c in chunks] == [10]


def test_chunk_03_zero_items() -> None:
    assert chunk_items([], size=10) == []


def test_chunk_default_size_is_10() -> None:
    assert DEFAULT_CHUNK_SIZE == 10


def test_chunk_04_soft_cap_50() -> None:
    assert SOFT_CAP == 50
    kept, dropped = apply_soft_cap(_items([f"w{i}" for i in range(65)]))
    assert len(kept) == 50
    assert len(dropped) == 15
    assert [it.headword for it in dropped] == [f"w{i}" for i in range(50, 65)]


def test_chunk_04_under_cap_drops_nothing() -> None:
    kept, dropped = apply_soft_cap(_items([f"w{i}" for i in range(10)]))
    assert len(kept) == 10
    assert dropped == []


def test_chunk_05_duplicate_word_coalesced() -> None:
    deduped = dedupe_items(_items(["run", "jump", "run"]), user_id=1)
    assert [it.headword for it in deduped] == ["run", "jump"]


# --- IDEM ----------------------------------------------------------------


def test_idem_01_job_id_deterministic() -> None:
    assert job_id(42, "run") == job_id(42, "run")


def test_idem_02_user_scoped() -> None:
    assert job_id(1, "run") != job_id(2, "run")


def test_idem_05_case_and_whitespace_folded() -> None:
    assert job_id(1, "Run") == job_id(1, "run")
    assert job_id(1, "  run ") == job_id(1, "run")
    assert normalize_word_key("  Run ") == "run"


def test_job_id_format() -> None:
    assert job_id(7, "run") == "w:7:run"
