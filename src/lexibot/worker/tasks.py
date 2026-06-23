"""ARQ worker tasks: chunk enrichment -> per-word pipeline.

``process_chunk`` runs one structured LLM call for a chunk, then fans out per-word work
through the :class:`~lexibot.core.pipeline.Pipeline`. Validation failures fall back to
per-item LLM calls (VALID-02/03) before a word is finally skipped. ``AnkiUnavailable`` is
re-raised so ARQ retries the job later (offline queueing, RETRY-04).

Progress is published to a single Redis key per job, ``lexibot:progress:{jid}``, holding a
JSON object mapping each headword to its current step (``queued`` / ``llm`` / ``tts`` /
``anki`` / ``done`` / ``rewritten`` / ``failed``). The bot polls that key to render the
real-time stepper, so each state transition here is a read-modify-write on that object.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from lexibot.core.enums import ItemOutcome
from lexibot.core.exceptions import AnkiUnavailable, LLMError
from lexibot.core.models import RawItem, Sense
from lexibot.core.pipeline import Pipeline, WordResult
from lexibot.llm.ports import LanguageModel

log = structlog.get_logger(__name__)

_PROGRESS_TTL = 3600


async def _update_progress(redis: Any, progress_key: str, headword: str, state: str) -> None:
    """Read-modify-write one headword's state in the job's progress JSON object.

    The bot publishes the initial object (all words ``queued``) before enqueuing, so this
    only needs to patch a single field. A plain GET/SET round-trip is sufficient at this
    scale; the stepper is best-effort and a lost transition self-corrects on the next poll.
    """
    raw = await redis.get(progress_key)
    progress: dict[str, str] = {}
    if raw is not None:
        try:
            progress = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except (ValueError, AttributeError):
            progress = {}
    progress[headword] = state
    await redis.set(progress_key, json.dumps(progress), ex=_PROGRESS_TTL)


async def _enrich_with_fallback(ctx: dict[str, Any], items: list[RawItem]) -> list[Sense | None]:
    """Enrich a chunk; on failure or a short result, retry the missing items one-by-one."""
    llm: LanguageModel = ctx["llm"]
    try:
        senses = await llm.enrich(items)
    except LLMError:
        senses = []

    if len(senses) == len(items):
        return list(senses)

    resolved: list[Sense | None] = []
    for item in items:
        matched = None
        for s in senses:
            if s.headword.strip().casefold() == item.headword.strip().casefold():
                matched = s
                break
        if matched:
            resolved.append(matched)
        else:
            try:
                one = await llm.enrich([item], sense_hint=item.sense_hint)
                resolved.append(one[0] if one else None)
            except LLMError:
                resolved.append(None)
    return resolved


async def process_chunk(
    ctx: dict[str, Any], items: list[dict[str, Any]], user_id: int
) -> list[dict[str, str]]:
    """Process one chunk of items and return per-word outcomes for the summary.

    Each word's pipeline state is mirrored into ``lexibot:progress:{job_id}`` so the bot
    can render the real-time stepper: ``llm`` before enrichment, ``tts``/``anki`` from the
    pipeline callbacks, then ``done``/``rewritten``/``failed`` on completion.
    """
    pipeline: Pipeline = ctx["pipeline"]
    raw = [RawItem(**it) for it in items]

    redis = ctx.get("redis")
    jid = ctx.get("job_id")
    progress_key = f"lexibot:progress:{jid}" if (redis and jid) else None

    # Sync remote Anki collection first to retrieve any changes made on other devices
    try:
        await ctx["anki"].sync()
    except Exception as e:
        log.error("anki.sync_before.failed", error=str(e))

    # Mark every word as in-LLM before the (shared) enrichment call so the stepper reflects
    # the actual batched call rather than per-item serial progress.
    if progress_key:
        for it in raw:
            await _update_progress(redis, progress_key, it.headword, "llm")

    senses = await _enrich_with_fallback(ctx, raw)

    results: list[dict[str, str]] = []
    for item, sense in zip(raw, senses, strict=False):
        headword = item.headword
        if sense is None:
            if progress_key:
                await _update_progress(redis, progress_key, headword, "failed")
            results.append(
                {
                    "word": headword,
                    "outcome": ItemOutcome.SKIPPED,
                    "error": "LLM enrichment failed",
                }
            )
            continue

        # Bind the headword into the callback so the loop variable isn't captured late.
        async def on_state_change(state: str, _hw: str = headword) -> None:
            if progress_key:
                await _update_progress(redis, progress_key, _hw, state)

        try:
            res = await pipeline.process(sense, on_state_change=on_state_change)
            final_state = "done" if res.outcome == ItemOutcome.ADDED else "rewritten"
            if progress_key:
                await _update_progress(redis, progress_key, sense.headword, final_state)

            results.append(
                {
                    "word": res.word_field,
                    "outcome": res.outcome,
                    "headword": sense.headword,
                    "pos": sense.part_of_speech,
                    "si_meaning": sense.si_meaning,
                    "en_meaning": sense.en_meaning,
                    "sentence_1": sense.sentence_1,
                    "sentence_2": sense.sentence_2,
                }
            )
        except AnkiUnavailable:
            log.warning("anki.unavailable.requeue", word=sense.word_field)
            if progress_key:
                await _update_progress(redis, progress_key, sense.headword, "failed")
            raise
        except Exception as e:
            log.error("word.processing.failed", word=sense.word_field, error=str(e))
            if progress_key:
                await _update_progress(redis, progress_key, sense.headword, f"failed: {e}")
            results.append(
                {
                    "word": sense.word_field,
                    "outcome": ItemOutcome.SKIPPED,
                    "error": str(e),
                }
            )

    try:
        await ctx["anki"].sync()
    except Exception as e:
        log.error("anki.sync.failed", error=str(e))
    return results


def outcome_skipped(word_field: str) -> WordResult:
    """Helper for callers that need to record a skip without running the pipeline."""
    return WordResult(word_field, ItemOutcome.SKIPPED)
