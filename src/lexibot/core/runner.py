"""In-process pipeline runner (replaces ARQ/Redis).

A broker is unnecessary at single-user volume. Handlers schedule chunk work on the
asyncio loop under an :class:`asyncio.Semaphore`; progress and transient state live
in memory. Orchestration (per-chunk LLM → per-word fan-out → 3-clip TaskGroup →
media store → upsert → debounced sync) is relocated here from ``worker/tasks.py``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import structlog

from lexibot.core.enums import ItemOutcome
from lexibot.core.exceptions import AnkiUnavailable, LLMError
from lexibot.core.models import RawItem, Sense
from lexibot.core.pipeline import Pipeline
from lexibot.db.repositories import add_audit_event, get_user_model, record_processed_item
from lexibot.llm.ports import LanguageModel
from lexibot.observability.alerts import AdminAlerter
from lexibot.worker.enqueue import job_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from lexibot.config import Settings

log = structlog.get_logger(__name__)

DEFAULT_PROGRESS_TTL_S = 3600


# --- Lightweight key/value state -------------------------------------------


class StateStore:
    """In-memory key/value store with optional TTL (replaces Redis for bot state)."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float | None, bytes]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at is not None and time.monotonic() >= expires_at:
                self._data.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:
        async with self._lock:
            expires_at = time.monotonic() + ex if ex else None
            payload = value if isinstance(value, bytes) else value.encode()
            self._data[key] = (expires_at, payload)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)


# --- Per-batch progress ----------------------------------------------------


class BatchProgress:
    """Per-chunk progress + results, read by the monitor task while polling ``done``."""

    __slots__ = ("_completed", "done", "results", "states")

    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.results: list[dict[str, str]] = []
        self.done: asyncio.Event = asyncio.Event()
        self._completed: bool = False

    def mark_completed(self, results: list[dict[str, str]]) -> None:
        self.results = results
        self._completed = True
        self.done.set()

    def is_running(self) -> bool:
        return not self._completed


# --- Pipeline runner -------------------------------------------------------


class PipelineRunner:
    """Schedules bounded chunk work as asyncio tasks; drains on shutdown."""

    def __init__(
        self,
        *,
        pipeline: Pipeline,
        llm: LanguageModel,
        anki: Any,
        engine: AsyncEngine | None,
        alerter: AdminAlerter | None,
        settings: Settings,
    ) -> None:
        self._pipeline = pipeline
        self._llm = llm
        self._anki = anki
        self._engine = engine
        self._alerter = alerter
        self._settings = settings
        self._chunk_sem = asyncio.Semaphore(settings.pipeline_concurrency)
        self._tasks: set[asyncio.Task[Any]] = set()
        self.state = StateStore()
        self._batches: dict[str, BatchProgress] = {}

    # --- Bot-facing surface -----------------------------------------------

    def submit_chunk(
        self,
        *,
        user_id: int,
        items: list[RawItem],
    ) -> tuple[str, BatchProgress]:
        """Schedule one chunk and return ``(job_id, BatchProgress)``.

        Coalesces rapid duplicate submissions with the same job id (returns the
        existing in-flight handle). The Anki upsert is the cross-process backstop.
        """
        jid = job_id(user_id, "+".join(i.headword for i in items))
        existing = self._batches.get(jid)
        if existing is not None and existing.is_running():
            return jid, existing

        progress = BatchProgress()
        for item in items:
            progress.states[item.headword.strip().casefold()] = "queue"
        self._batches[jid] = progress

        task = asyncio.create_task(
            self._run_chunk(jid=jid, user_id=user_id, items=list(items), progress=progress),
            name=f"pipeline:{jid}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return jid, progress

    def get_progress(self, jid: str) -> BatchProgress | None:
        """Return the live progress handle for a job id (best-effort)."""
        return self._batches.get(jid)

    async def drain(self, *, timeout_s: float = 30.0) -> None:
        """Wait for in-flight tasks, then cancel the remainder on timeout."""
        pending = [t for t in self._tasks if not t.done()]
        if not pending:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=timeout_s,
            )
        except TimeoutError:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    # --- Internal pipeline logic ------------------------------------------

    async def _publish_progress(self, jid: str, progress: BatchProgress) -> None:
        """Mirror in-memory progress to the StateStore under the legacy key."""
        await self.state.set(
            f"lexibot:progress:{jid}",
            json.dumps(progress.states),
            ex=DEFAULT_PROGRESS_TTL_S,
        )

    async def _enrich_with_fallback(self, items: list[RawItem]) -> list[Sense | None]:
        """One structured LLM call per chunk; per-item fallback on failure/short result."""
        try:
            senses = await self._llm.enrich(items)
        except LLMError:
            senses = []

        if len(senses) == len(items):
            return list(senses)

        resolved: list[Sense | None] = []
        for item in items:
            matched = next(
                (
                    s
                    for s in senses
                    if s.headword.strip().casefold() == item.headword.strip().casefold()
                ),
                None,
            )
            if matched:
                resolved.append(matched)
            else:
                try:
                    one = await self._llm.enrich([item], sense_hint=item.sense_hint)
                    resolved.append(one[0] if one else None)
                except LLMError:
                    resolved.append(None)
        return resolved

    async def _run_chunk(
        self,
        *,
        jid: str,
        user_id: int,
        items: list[RawItem],
        progress: BatchProgress,
    ) -> list[dict[str, str]]:
        """Process one chunk end-to-end and store results on ``progress``."""
        async with self._chunk_sem:
            if self._engine is not None:
                user_model = await get_user_model(self._engine, user_id)
                if user_model:
                    self._llm.set_model(user_model)

            # Sync remote Anki collection first to retrieve any changes made on other devices.
            try:
                await self._anki.sync()
            except Exception as e:
                log.error("anki.sync_before.failed", error=str(e))

            # Mark every word as in-LLM before the shared enrichment call so the
            # stepper reflects the actual batched call rather than per-item serial progress.
            for it in items:
                progress.states[it.headword.strip().casefold()] = "llm"
            await self._publish_progress(jid, progress)

            senses = await self._enrich_with_fallback(items)

            results: list[dict[str, str]] = []
            for item, sense in zip(items, senses, strict=False):
                headword = item.headword
                if sense is None:
                    progress.states[headword.strip().casefold()] = "failed"
                    await self._publish_progress(jid, progress)
                    await self._persist_outcome(
                        jid, user_id, headword, str(ItemOutcome.SKIPPED), "LLM enrichment failed"
                    )
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
                    progress.states[_hw.strip().casefold()] = state
                    await self._publish_progress(jid, progress)

                try:
                    res = await self._pipeline.process(sense, on_state_change=on_state_change)
                    final_state = "done" if res.outcome == ItemOutcome.ADDED else "rewritten"
                    progress.states[sense.headword.strip().casefold()] = final_state
                    await self._publish_progress(jid, progress)

                    await self._persist_outcome(
                        jid,
                        user_id,
                        res.word_field,
                        str(res.outcome),
                        f"audio_failed={res.audio_failed}",
                    )
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
                    log.warning("anki.unavailable.skipped", word=sense.word_field)
                    progress.states[sense.headword.strip().casefold()] = "failed"
                    await self._publish_progress(jid, progress)
                    await self._persist_outcome(
                        jid, user_id, sense.word_field, str(ItemOutcome.SKIPPED), "Anki unavailable"
                    )
                    results.append(
                        {
                            "word": sense.word_field,
                            "outcome": ItemOutcome.SKIPPED,
                            "error": "Anki unavailable",
                        }
                    )
                    if self._alerter is not None:
                        await self._alerter.alert(
                            f"Anki unavailable; chunk {jid} could not complete."
                        )
                    # TODO(review): the previous ARQ worker re-raised AnkiUnavailable so the
                    # broker retried the job with backoff. There is no equivalent durable
                    # SQLite-backed pending queue today (only idempotency outcomes live in
                    # SQLite), so for now the chunk completes with skipped words and the
                    # user is alerted. Implement a durable SQLite queue + auto-flush loop
                    # if cross-restart durability is required.
                except Exception as e:
                    log.error("word.processing.failed", word=sense.word_field, error=str(e))
                    progress.states[sense.headword.strip().casefold()] = f"failed: {e}"
                    await self._publish_progress(jid, progress)
                    await self._persist_outcome(
                        jid, user_id, sense.word_field, str(ItemOutcome.SKIPPED), str(e)
                    )
                    results.append(
                        {
                            "word": sense.word_field,
                            "outcome": ItemOutcome.SKIPPED,
                            "error": str(e),
                        }
                    )

            try:
                await self._anki.sync()
            except Exception as e:
                log.error("anki.sync.failed", error=str(e))

            progress.mark_completed(results)
            return results

    async def _persist_outcome(
        self,
        jid: str,
        user_id: int,
        word_field: str,
        outcome: str,
        detail: str = "",
    ) -> None:
        if self._engine is None:
            return
        try:
            await record_processed_item(
                self._engine,
                job_id=jid,
                user_id=user_id,
                word_field=word_field,
                outcome=outcome,
            )
            await add_audit_event(
                self._engine,
                user_id=user_id,
                event=f"word:{outcome}",
                detail=detail or word_field,
            )
        except Exception as exc:
            log.warning("db.audit.failed", error=str(exc))
