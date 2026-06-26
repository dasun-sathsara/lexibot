"""Telegram rendering: batch summaries + safe markdown.

Outcome classification (added / rewritten / skipped) is pure logic and unit-testable;
``markdownify`` from telegramify-markdown escapes user text so a word with markdown-special
characters cannot break formatting (SUM-04).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

import telegramify_markdown

from lexibot.core.enums import ItemOutcome

TELEGRAM_MAX_LEN = 4096

_BUCKET_LABEL = {
    ItemOutcome.ADDED: "\u2705 Added",
    ItemOutcome.REWRITTEN: "\u267b\ufe0f Rewritten",
    ItemOutcome.SKIPPED: "\u23ed\ufe0f Skipped",
}

POS_NAMES = {
    "n": "noun",
    "v": "verb",
    "adj": "adjective",
    "adv": "adverb",
    "prep": "preposition",
    "conj": "conjunction",
    "pron": "pronoun",
    "phr": "phrase",
}


def render_card_preview(results: list[dict[str, str]]) -> str:
    """Render a preview of completed cards in the batch."""
    completed = [
        r for r in results if r.get("outcome") in (ItemOutcome.ADDED, ItemOutcome.REWRITTEN)
    ]
    if not completed:
        parts = ["❌ **Batch Processing Failed**", ""]
        for res in results:
            word = res.get("word", "unknown")
            err = res.get("error", "unknown error")
            parts.append(f"* `{word}` — Failed: {err}")
        return "\n".join(parts)

    parts = ["✅ **Batch Processing Complete**"]
    for i, res in enumerate(completed, 1):
        pos = res.get("pos", "")
        pos_full = POS_NAMES.get(pos, pos)
        hw = res.get("headword", "")
        si = res.get("si_meaning", "")
        en = res.get("en_meaning", "")
        ex1 = res.get("sentence_1", "")
        ex2 = res.get("sentence_2", "")

        parts.append("")
        parts.append("---")
        parts.append(f"**{i}. {hw}** ({pos_full})")
        parts.append(f"* **Meaning**: {si}")
        parts.append(f"* **Definition**: {en}")
        parts.append("* **Examples**:")
        parts.append(f"  1. *{ex1}*")
        if ex2:
            parts.append(f"  2. *{ex2}*")

    return "\n".join(parts)


def safe_markdown(text: str) -> str:
    """Convert text to Telegram MarkdownV2 format safely."""
    return str(telegramify_markdown.markdownify(text))


def summarize_counts(outcomes: Iterable[ItemOutcome]) -> Counter[ItemOutcome]:
    """Tally outcomes into a counter (SUM-01/02)."""
    return Counter(outcomes)


def render_summary(results: list[tuple[str, ItemOutcome]]) -> str:
    """Render a batch summary grouped by outcome bucket, truncated to Telegram limits.

    ``results`` is a list of ``(word, outcome)``. Output never exceeds
    :data:`TELEGRAM_MAX_LEN` characters (SUM-03).
    """
    counts = summarize_counts(o for _, o in results)
    header_parts = [
        f"{_BUCKET_LABEL[o].split()[0]} {counts.get(o, 0)}"
        for o in (ItemOutcome.ADDED, ItemOutcome.REWRITTEN, ItemOutcome.SKIPPED)
    ]
    lines = [" ".join(header_parts), ""]

    for outcome in (ItemOutcome.ADDED, ItemOutcome.REWRITTEN, ItemOutcome.SKIPPED):
        words = [w for w, o in results if o is outcome]
        if not words:
            continue
        lines.append(f"{_BUCKET_LABEL[outcome]}:")
        lines.extend(f"  \u2022 {w}" for w in words)

    text = "\n".join(lines)
    if len(text) <= TELEGRAM_MAX_LEN:
        return text
    # Truncate with an explicit marker rather than silently dropping content.
    marker = "\n\u2026 (truncated)"
    return text[: TELEGRAM_MAX_LEN - len(marker)] + marker
