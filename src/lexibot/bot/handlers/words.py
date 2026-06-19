"""Free-text word ingestion.

Parses the message, applies the soft cap and dedup, chunks the items, and enqueues one
``process_chunk`` job per chunk with a deterministic id so rapid resends coalesce. A single
status message is posted and later edited in place with the batch summary.
"""

from __future__ import annotations

import asyncio
import json

import structlog
from aiogram import Bot, Router
from aiogram.types import Message
from arq.connections import ArqRedis
from arq.jobs import Job

from lexibot.bot.keyboards import completed_keyboard
from lexibot.bot.rendering import render_card_preview, render_summary, safe_markdown
from lexibot.core.enums import ItemOutcome
from lexibot.core.parsing import parse_message
from lexibot.worker.enqueue import (
    DEFAULT_CHUNK_SIZE,
    apply_soft_cap,
    chunk_items,
    dedupe_items,
    job_id,
)

log = structlog.get_logger(__name__)

router = Router(name="words")

_background_tasks: set[asyncio.Task[None]] = set()


async def _monitor_jobs(
    status: Message,
    jobs: list[Job],
    word_keys: list[str],
    arq: ArqRedis,
    bot: Bot,
) -> None:
    import json

    from arq.jobs import JobStatus

    last_text = ""
    while True:
        all_finished = True
        for job in jobs:
            try:
                js = await job.status()
                if js in (JobStatus.queued, JobStatus.in_progress):
                    all_finished = False
                    break
            except Exception:
                pass

        progress_map: dict[str, str] = {}
        for job in jobs:
            try:
                val = await arq.get(f"lexibot:progress:{job.job_id}")
                if val:
                    data = json.loads(val.decode() if isinstance(val, bytes) else val)
                    progress_map.update(data)
            except Exception:
                pass

        states = {}
        for word in word_keys:
            target = word.strip().casefold()
            states[word] = progress_map.get(target, "queue")

        def format_state(state: str) -> str:
            STATE_TEXT = {
                "queue": "💤 In queue...",
                "llm": "🧠 LLM: Generating meaning & examples...",
                "tts": "🔊 TTS: Synthesizing voice audio...",
                "anki": "📥 Anki: Saving card & media...",
                "done": "✅ Added successfully!",
                "rewritten": "♻️ Rewritten!",
            }
            if state.startswith("failed"):
                if ":" in state:
                    err = state.split(":", 1)[1].strip()
                    return f"❌ Failed: {err}"
                return "❌ Failed"
            return STATE_TEXT.get(state, "💤 In queue...")

        words_count = len(word_keys)
        plural = "s" if words_count > 1 else ""
        header = f"⏳ **Processing {words_count} word{plural}...**"
        msg_parts = [header, ""]
        for word in word_keys:
            state = states[word]
            formatted = format_state(state)
            msg_parts.append(f"* `{word}` — {formatted}")

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

        if all_finished:
            break

        await asyncio.sleep(1.5)

    results = []
    for job in jobs:
        try:
            job_res = await job.result()
            if job_res:
                results.extend(job_res)
        except Exception as e:
            log.error("job.result.failed", error=str(e))

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

    try:
        await arq.set(f"batch_results:{status.message_id}", json.dumps(results), ex=86400)
    except Exception as e:
        log.error("batch_results.save.failed", error=str(e))

    is_batch = len(word_keys) > 1
    if is_batch:
        summary_items = []
        for r in results:
            w = r.get("word") or r.get("headword") or "unknown"
            raw_outcome = r.get("outcome", "skipped")
            try:
                outcome = ItemOutcome(raw_outcome)
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
async def ingest_words(message: Message, arq: ArqRedis, bot: Bot) -> None:
    user = message.from_user
    if user is None:
        return
    items = parse_message(message.text or "")
    if not items:
        await message.answer("Send me a word or a list of words.")
        return

    items = dedupe_items(items, user_id=user.id)
    kept, dropped = apply_soft_cap(items)

    note = ""
    if dropped:
        note = f"\n\u26a0\ufe0f Only the first {len(kept)} of {len(kept) + len(dropped)} processed."

    status = await message.answer(f"\u23f3 Queued {len(kept)} word(s)\u2026{note}")

    jobs: list[Job] = []
    word_keys: list[str] = []
    for chunk in chunk_items(kept, size=DEFAULT_CHUNK_SIZE):
        jid = job_id(user.id, "+".join(i.headword for i in chunk))

        initial_progress = {item.headword.strip().casefold(): "queue" for item in chunk}
        await arq.set(f"lexibot:progress:{jid}", json.dumps(initial_progress), ex=3600)

        job = await arq.enqueue_job(
            "process_chunk",
            [item.model_dump() for item in chunk],
            user.id,
            _job_id=jid,
        )
        if job is None:
            job = Job(jid, arq)
        jobs.append(job)

        for item in chunk:
            word_keys.append(item.headword)

    task = asyncio.create_task(_monitor_jobs(status, jobs, word_keys, arq, bot))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
