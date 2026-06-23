"""Per-word orchestration: LLM -> TTS -> Anki.

The three audio clips are generated with :class:`asyncio.TaskGroup` so a failure cancels its
siblings and raises an :class:`ExceptionGroup`. The pipeline maps that to graceful partial
failure: the card is still written (text only) and audio is flagged for later retry
(PIPE-02/03). Concurrency is bounded by two semaphores — ``min(#keys, 3)`` for LLM chunks and
4 for TTS calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import structlog

from lexibot.config import Settings
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
    def from_settings(cls, settings: Settings) -> PipelineLimits:
        return cls(
            tts=settings.tts_concurrency,
            llm_chunks=min(max(len(settings.gemini_api_keys), 1), settings.max_llm_chunks),
        )


async def synthesize_clips(
    sense: Sense, tts: Synthesizer, *, tts_sem: asyncio.Semaphore
) -> tuple[bytes | None, bytes | None, bytes | None]:
    """Generate (word, sentence_1, sentence_2) audio concurrently.

    Returns a tuple with the synthesized bytes for each clip. Individual failures are
    logged and returned as ``None`` so the caller can build a card with whatever audio
    succeeded instead of discarding partial progress.
    """

    async def _one(text: str, *, slow: bool) -> bytes | None:
        async with tts_sem:
            try:
                return await tts.synthesize(text, slow=slow)
            except TTSError:
                log.warning("tts.clip_failed", word=sense.word_field, text=text)
                return None

    async with asyncio.TaskGroup() as tg:
        word = tg.create_task(_one(sense.headword, slow=True))
        ex1 = tg.create_task(_one(sense.sentence_1, slow=False))
        ex2 = tg.create_task(_one(sense.sentence_2, slow=False))

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

    async def process(
        self,
        sense: Sense,
        on_state_change: Callable[[str], Awaitable[None]] | None = None,
    ) -> WordResult:
        """Process one enriched word end-to-end."""
        if not sense.is_valid_word:
            return WordResult(sense.word_field, ItemOutcome.SKIPPED)

        if on_state_change:
            await on_state_change("tts")
        audio = await synthesize_clips(sense, self._tts, tts_sem=self._tts_sem)

        if on_state_change:
            await on_state_change("anki")
        card: Card = Card.from_sense(sense, audio=audio, gender=self._gender)
        outcome = await self._anki.upsert(card)
        return WordResult(sense.word_field, outcome, audio_failed=audio is None)
