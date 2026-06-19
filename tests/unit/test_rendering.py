"""SUM-01..04 — outcome classification + batch summary.

These are pure-logic (no aiogram Bot needed): they exercise the counting and rendering
functions directly.
"""

from __future__ import annotations

from lexibot.bot.rendering import (
    TELEGRAM_MAX_LEN,
    render_summary,
    safe_markdown,
    summarize_counts,
)
from lexibot.core.enums import ItemOutcome


def test_sum_01_counts_and_buckets() -> None:
    results = [
        ("v:run", ItemOutcome.ADDED),
        ("n:bank", ItemOutcome.REWRITTEN),
        ("xyzzy", ItemOutcome.SKIPPED),
        ("v:jump", ItemOutcome.ADDED),
    ]
    counts = summarize_counts(o for _, o in results)
    assert counts[ItemOutcome.ADDED] == 2
    assert counts[ItemOutcome.REWRITTEN] == 1
    assert counts[ItemOutcome.SKIPPED] == 1

    text = render_summary(results)
    assert "v:run" in text and "v:jump" in text
    assert "n:bank" in text
    assert "xyzzy" in text


def test_sum_02_all_skipped() -> None:
    results = [("xyzzy", ItemOutcome.SKIPPED), ("qwerty", ItemOutcome.SKIPPED)]
    text = render_summary(results)
    assert "\u2705 0" in text  # zero added
    assert "Skipped" in text
    assert "xyzzy" in text and "qwerty" in text


def test_sum_03_respects_length_limit() -> None:
    results = [(f"v:word{i}", ItemOutcome.ADDED) for i in range(5000)]
    text = render_summary(results)
    assert len(text) <= TELEGRAM_MAX_LEN


def test_sum_04_markdown_special_chars_escaped() -> None:
    # Stray markdown-special characters in a word must be escaped so they cannot break
    # MarkdownV2 formatting (telegramify-markdown preserves *valid* markup but escapes the
    # rest, e.g. '+', '(', ')', '.').
    out = safe_markdown("c++ (a.k.a. v2.0)")
    for ch in ("+", "(", ")", "."):
        assert f"\\{ch}" in out
