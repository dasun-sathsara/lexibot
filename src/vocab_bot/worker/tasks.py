"""ARQ worker tasks: chunk enrichment -> per-word pipeline (architecture §4, §8).

``process_chunk`` runs one structured LLM call for a chunk, then fans out per-word work
through the :class:`~vocab_bot.core.pipeline.Pipeline`. Validation failures fall back to
per-item LLM calls (VALID-02/03) before a word is finally skipped. ``AnkiUnavailable`` is
re-raised so ARQ retries the job later (offline queueing, RETRY-04).
"""

from __future__ import annotations

from typing import Any

import structlog

from vocab_bot.core.enums import ItemOutcome
from vocab_bot.core.exceptions import AnkiUnavailable, LLMError
from vocab_bot.core.models import RawItem, Sense
from vocab_bot.core.pipeline import Pipeline, WordResult
from vocab_bot.llm.ports import LanguageModel

log = structlog.get_logger(__name__)


async def _enrich_with_fallback(ctx: dict[str, Any], items: list[RawItem]) -> list[Sense]:
    """Enrich a chunk; on failure or a short result, retry the missing items one-by-one."""
    llm: LanguageModel = ctx["llm"]
    try:
        senses = await llm.enrich(items)
    except LLMError:
        senses = []

    if len(senses) == len(items):
        return senses

    # Per-item fallback for anything the chunk call did not return (VALID-03).
    resolved: list[Sense] = list(senses)
    for item in items[len(senses) :]:
        try:
            one = await llm.enrich([item], sense_hint=item.sense_hint)
        except LLMError:
            one = []
        if one:
            resolved.append(one[0])
    return resolved


async def process_chunk(
    ctx: dict[str, Any], items: list[dict[str, Any]], user_id: int
) -> list[dict[str, str]]:
    """Process one chunk of items and return per-word outcomes for the summary."""
    pipeline: Pipeline = ctx["pipeline"]
    raw = [RawItem(**it) for it in items]
    senses = await _enrich_with_fallback(ctx, raw)

    results: list[WordResult] = []
    for sense in senses:
        try:
            results.append(await pipeline.process(sense))
        except AnkiUnavailable:
            log.warning("anki.unavailable.requeue", word=sense.word_field)
            raise  # let ARQ retry the whole job later
    return [{"word": r.word_field, "outcome": r.outcome} for r in results]


def outcome_skipped(word_field: str) -> WordResult:
    """Helper for callers that need to record a skip without running the pipeline."""
    return WordResult(word_field, ItemOutcome.SKIPPED)
