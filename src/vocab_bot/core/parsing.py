"""Message parsing: inbound text -> candidate items (test-spec §1.1, §2).

Light pre-splitting only. We never try to decide whether an item is a bare word or a
``word + sense`` beyond locating an explicit sense delimiter; deeper intent (typo
correction, POS, lemma) is left to the LLM step.
"""

from __future__ import annotations

import re

from vocab_bot.core.models import RawItem

# Item separators: newlines and commas (spaces are preserved within an item).
_ITEM_SPLIT = re.compile(r"[,\n]")

# Sense delimiters. Hyphen and em-dash require surrounding spaces so that hyphenated
# words (``well-being``) are not split; the colon form matches a leading ``headword:``
# token (no space before the colon) followed by the meaning.
_SPACED_DELIM = re.compile(r"\s+[-\u2014]\s+")
_COLON_DELIM = re.compile(r"^([^\s:]+):\s*(.*)$", re.DOTALL)

# Markdown / decorative punctuation stripped from the edges of a bare item.
_EDGE_NOISE = re.compile(r"^[\s*_`~>#\"'.!?]+|[\s*_`~\"'.!?]+$")


def _clean(text: str) -> str:
    """Trim whitespace and strip surrounding markdown/punctuation noise (PARSE-14)."""
    return _EDGE_NOISE.sub("", text.strip())


def _split_sense(item: str) -> tuple[str, str | None]:
    """Split a single item into ``(headword, sense_hint)`` on the first delimiter only."""
    item = item.strip()
    # Spaced hyphen / em-dash: split on the first occurrence.
    spaced = _SPACED_DELIM.split(item, maxsplit=1)
    if len(spaced) == 2:
        head, hint = spaced
        return _clean(head), _normalize_hint(hint)

    # Leading-token colon form: ``bank: meaning``.
    colon = _COLON_DELIM.match(item)
    if colon:
        head, hint = colon.group(1), colon.group(2)
        return _clean(head), _normalize_hint(hint)

    return _clean(item), None


def _normalize_hint(hint: str) -> str | None:
    """An empty/whitespace-only hint becomes ``None`` (PARSE-11)."""
    cleaned = hint.strip()
    return cleaned or None


def parse_message(raw: str) -> list[RawItem]:
    """Split an inbound message into candidate :class:`RawItem` objects.

    Empty/whitespace-only items are dropped; leading/trailing whitespace and surrounding
    markdown are trimmed; case is preserved.
    """
    items: list[RawItem] = []
    for chunk in _ITEM_SPLIT.split(raw):
        if not chunk.strip():
            continue
        headword, sense_hint = _split_sense(chunk)
        if not headword:
            continue
        items.append(RawItem(headword=headword, sense_hint=sense_hint))
    return items
