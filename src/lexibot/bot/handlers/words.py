"""Free-text word ingestion: parse → dedup → chunk → dispatch to the runner."""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Router
from aiogram.types import Message

from lexibot.bot.keyboards import completed_keyboard
from lexibot.bot.rendering import render_card_preview, render_summary, safe_markdown
from lexibot.bot.task_registry import spawn_task
from lexibot.config import get_settings
from lexibot.core.enums import ItemOutcome
from lexibot.core.parsing import parse_message
from lexibot.core.runner import BatchProgress, PipelineRunner, StateStore
from lexibot.worker.enqueue import (
    apply_soft_cap,
    chunk_items,
    dedupe_items,
)

log = structlog.get_logger(__name__)

router = Router(name="words")


def _format_state(state: str) -> str:
    """Render one headword's pipeline step for the live stepper."""
    STATE_TEXT = {
        "queue": "\U0001f4a4 In queue...",
        "llm": "\U0001f9e0 LLM: Generating meaning & examples...",
        "tts": "\U0001f50a TTS: Synthesizing voice audio...",
        "anki": "\U0001f4e5 Anki: Saving card & media...",
        "done": "\u2705 Added successfully!",
        "rewritten": "\u267b\ufe0f Rewritten!",
    }
    if state.startswith("failed"):
        if ":" in state:
            err = state.split(":", 1)[1].strip()
            return f"\u274c Failed: {err}"
        return "\u274c Failed"
    return STATE_TEXT.get(state, "\U0001f4a4 In queue...")


async def _monitor_progress(
    status: Message,
    handles: list[tuple[str, BatchProgress]],
    word_keys: list[str],
    state: StateStore,
    bot: Bot,
) -> None:
    """Poll in-memory BatchProgress handles and edit the status message in place."""
    last_text = ""
    while True:
        all_done = all(h.done.is_set() for _, h in handles)

        # The runner mirrors in-memory progress to the StateStore under the legacy key
        # for any consumer that still reads it; here we read it directly off the handles.
        progress_map: dict[str, str] = {}
        for _, handle in handles:
            progress_map.update(handle.states)

        states = {word: progress_map.get(word.strip().casefold(), "queue") for word in word_keys}

        words_count = len(word_keys)
        plural = "s" if words_count > 1 else ""
        header = f"\u23f3 **Processing {words_count} word{plural}...**"
        msg_parts = [header, ""]
        for word in word_keys:
            formatted = _format_state(states[word])
            msg_parts.append(f"* `{word}` \u2014 {formatted}")

        text = "\n".join(msg_parts)
        summary_text = safe_markdown(text)

        if summary_text != last_text:
            try:
                await bot.edit_message_text(
                    text=summary_text,
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                    parse_mode="MarkdownV2",
                )
                last_text = summary_text
            except Exception as e:
                log.error("job.monitor.edit_message.failed", error=str(e))

        if all_done:
            break

        await asyncio.sleep(1.5)

    # Collect per-word results from each completed handle.
    results = []
    for _, handle in handles:
        results.extend(handle.results)

    # Backfill any word that finished without a recorded result (defensive).
    for word in word_keys:
        matched = False
        for r in results:
            r_hw = r.get("headword", "").strip().casefold()
            r_w = r.get("word", "").split(":", 1)[-1].strip().casefold()
            target = word.strip().casefold()
            if r_hw == target or r_w == target:
                matched = True
                break
        if not matched:
            results.append(
                {
                    "word": word,
                    "outcome": ItemOutcome.SKIPPED,
                    "error": "Failed to complete processing",
                }
            )

    # Persist the batch results so callback handlers (Regen / Edit Meaning) can update the
    # original preview message in place. Mirrors the previous ``batch_results:<mid>`` key.
    try:
        import json

        await state.set(f"batch_results:{status.message_id}", json.dumps(results), ex=86400)
    except Exception as e:
        log.error("batch_results.save.failed", error=str(e))

    is_batch = len(word_keys) > 1
    if is_batch:
        summary_items = []
        for r in results:
            w = r.get("word") or r.get("headword") or "unknown"
            raw_outcome = r.get("outcome", ItemOutcome.SKIPPED)
            try:
                outcome = (
                    raw_outcome
                    if isinstance(raw_outcome, ItemOutcome)
                    else ItemOutcome(raw_outcome)
                )
            except ValueError:
                outcome = ItemOutcome.SKIPPED
            summary_items.append((w, outcome))
        preview_text = safe_markdown(render_summary(summary_items))
        kb = None
    else:
        preview_text = safe_markdown(render_card_preview(results))
        kb = completed_keyboard(results)

    try:
        await bot.edit_message_text(
            text=preview_text,
            chat_id=status.chat.id,
            message_id=status.message_id,
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
    except Exception as e:
        log.error("job.monitor.final_edit.failed", error=str(e))


@router.message()
async def ingest_words(
    message: Message, runner: PipelineRunner, state: StateStore, bot: Bot
) -> None:
    user = message.from_user
    if user is None:
        return
    items = parse_message(message.text or "")
    if not items:
        await message.answer("Send me a word or a list of words.")
        return

    settings = get_settings()
    items = dedupe_items(items, user_id=user.id)
    kept, dropped = apply_soft_cap(items, cap=settings.soft_cap)

    note = ""
    if dropped:
        note = f"\n\u26a0\ufe0f Only the first {len(kept)} of {len(kept) + len(dropped)} processed."

    status = await message.answer(f"\u23f3 Queued {len(kept)} word(s)\u2026{note}")

    handles: list[tuple[str, BatchProgress]] = []
    word_keys: list[str] = []
    for chunk in chunk_items(kept, size=settings.chunk_size):
        jid, progress = runner.submit_chunk(user_id=user.id, items=chunk)
        handles.append((jid, progress))
        for item in chunk:
            word_keys.append(item.headword)

    spawn_task(_monitor_progress(status, handles, word_keys, state, bot))
