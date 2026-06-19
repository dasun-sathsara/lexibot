"""Per-word orchestration: LLM -> TTS -> Anki.

The three audio clips are generated with :class:`asyncio.TaskGroup` so a failure cancels its
siblings and raises an :class:`ExceptionGroup`. The pipeline maps that to graceful partial
failure: the card is still written (text only) and audio is flagged for later retry
(PIPE-02/03). Concurrency is bounded by two semaphores — ``min(#keys, 3)`` for LLM chunks and
4 for TTS calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import structlog

from lexibot.core.enums import ItemOutcome
from lexibot.core.exceptions import TTSError
from lexibot.core.models import Card, Sense
from lexibot.tts.ports import Synthesizer

log = structlog.get_logger(__name__)

DEFAULT_TTS_CONCURRENCY = 4
DEFAULT_MAX_LLM_CHUNKS = 3


@runtime_checkable
class AnkiGatewayLike(Protocol):
    """Structural type for the Anki write path.

    Declared here (rather than imported from the anki package) to keep the dependency
    direction core <- adapters. Matches :meth:`AnkiGateway.upsert`.
    """

    async def upsert(self, card: Card) -> ItemOutcome: ...


@dataclass(slots=True)
class WordResult:
    """Outcome of processing a single word through the pipeline."""

    word_field: str
    outcome: ItemOutcome
    audio_failed: bool = False
    error: str | None = None


@dataclass(slots=True)
class PipelineLimits:
    """Concurrency limits derived from runtime configuration."""

    tts: int = DEFAULT_TTS_CONCURRENCY
    llm_chunks: int = DEFAULT_MAX_LLM_CHUNKS

    @classmethod
    def from_key_count(cls, num_keys: int, *, tts: int = DEFAULT_TTS_CONCURRENCY) -> PipelineLimits:
        return cls(tts=tts, llm_chunks=min(max(num_keys, 1), DEFAULT_MAX_LLM_CHUNKS))


async def synthesize_clips(
    sense: Sense, tts: Synthesizer, *, tts_sem: asyncio.Semaphore
) -> tuple[bytes, bytes, bytes] | None:
    """Generate (word, sentence_1, sentence_2) audio concurrently.

    Returns the three clips on success, or ``None`` if any clip failed (the whole group is
    cancelled and the failure is logged) so the caller can still build a text-only card.
    """

    async def _one(text: str, *, slow: bool) -> bytes:
        async with tts_sem:
            return await tts.synthesize(text, slow=slow)

    failed = False
    try:
        async with asyncio.TaskGroup() as tg:
            word = tg.create_task(_one(sense.headword, slow=True))
            ex1 = tg.create_task(_one(sense.sentence_1, slow=False))
            ex2 = tg.create_task(_one(sense.sentence_2, slow=False))
    except* TTSError as eg:
        log.warning("tts.partial_failure", word=sense.word_field, errors=len(eg.exceptions))
        failed = True
    if failed:
        return None
    return (word.result(), ex1.result(), ex2.result())


class Pipeline:
    """Builds and writes a card for a single enriched :class:`Sense`."""

    def __init__(
        self,
        tts: Synthesizer,
        anki: AnkiGatewayLike,
        *,
        gender: str = "female",
        limits: PipelineLimits | None = None,
    ) -> None:
        self._tts = tts
        self._anki = anki
        self._gender = gender
        self._limits = limits or PipelineLimits()
        self._tts_sem = asyncio.Semaphore(self._limits.tts)

    async def process(self, sense: Sense) -> WordResult:
        """Process one enriched word end-to-end."""
        if not sense.is_valid_word:
            return WordResult(sense.word_field, ItemOutcome.SKIPPED)

        audio = await synthesize_clips(sense, self._tts, tts_sem=self._tts_sem)
        card: Card = Card.from_sense(sense, audio=audio, gender=self._gender)
        outcome = await self._anki.upsert(card)
        return WordResult(sense.word_field, outcome, audio_failed=audio is None)
