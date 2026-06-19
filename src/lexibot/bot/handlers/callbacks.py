"""Preview callback handlers: Add / Regenerate / Fix sense / Discard."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from arq.connections import ArqRedis
from arq.jobs import Job

from lexibot.anki.connect import AnkiConnect, build_find_query
from lexibot.bot.keyboards import CB_ADD, CB_DISCARD, CB_FIX, CB_REGEN, completed_keyboard
from lexibot.bot.rendering import render_card_preview, safe_markdown
from lexibot.config import get_settings
from lexibot.core.models import FIELD_SI_MEANING

log = structlog.get_logger(__name__)

router = Router(name="callbacks")

_background_tasks: set[asyncio.Task[None]] = set()


@router.callback_query(F.data.startswith(f"{CB_ADD}:"))
async def on_add(query: CallbackQuery) -> None:
    await query.answer("Added \u2705")
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith(f"{CB_REGEN}:"))
async def on_regenerate(query: CallbackQuery) -> None:
    await query.answer("Regenerating\u2026")


@router.callback_query(F.data.startswith(f"{CB_FIX}:"))
async def on_fix(query: CallbackQuery) -> None:
    await query.answer("Reply with the intended meaning.")


@router.callback_query(F.data.startswith(f"{CB_DISCARD}:"))
async def on_discard(query: CallbackQuery) -> None:
    await query.answer("Discarded \u274c")
    if isinstance(query.message, Message):
        await query.message.delete()


# --- UX Improvement Callback Handlers ---


@router.callback_query(F.data.startswith("delete_card:"))
async def on_delete_card(query: CallbackQuery) -> None:
    if not query.data:
        return
    await query.answer("Deleting card...")
    word_field = query.data.split(":", 1)[1]
    settings = get_settings()
    async with httpx.AsyncClient() as http:
        client = AnkiConnect(settings.ankiconnect_url, http)
        q = build_find_query(settings.note_type, word_field)
        note_ids = await client.find_notes(q)
        if note_ids:
            await client.delete_notes(note_ids)
        await client.sync()

    headword = word_field.split(":", 1)[-1]
    if isinstance(query.message, Message):
        text = safe_markdown(f"🗑️ **Deleted**: `{headword}`")
        await query.message.edit_text(text=text, parse_mode="MarkdownV2", reply_markup=None)


@router.callback_query(F.data.startswith("edit_meaning:"))
async def on_edit_meaning(query: CallbackQuery, arq: ArqRedis) -> None:
    if not query.data:
        return
    await query.answer()
    word_field = query.data.split(":", 1)[1]
    headword = word_field.split(":", 1)[-1]

    if not isinstance(query.message, Message):
        return

    user_id = query.from_user.id
    message_id = query.message.message_id

    await arq.set(f"edit_state:{user_id}:{message_id}", word_field, ex=600)

    msg = f"✏️ **Edit Meaning**: Reply to this message with the new Sinhala meaning for `{headword}`"
    text = safe_markdown(msg)
    await query.message.edit_text(text=text, parse_mode="MarkdownV2", reply_markup=None)


async def is_edit_reply(message: Message, arq: ArqRedis) -> bool | dict[str, Any]:
    if not message.reply_to_message:
        return False
    user = message.from_user
    if not user:
        return False
    state_key = f"edit_state:{user.id}:{message.reply_to_message.message_id}"
    word_field_bytes = await arq.get(state_key)
    if not word_field_bytes:
        return False
    wb = word_field_bytes
    word_field = wb.decode() if isinstance(wb, bytes) else wb
    return {"word_field": word_field, "state_key": state_key}


@router.message(is_edit_reply)
async def on_edit_reply(
    message: Message,
    arq: ArqRedis,
    word_field: str,
    state_key: str,
) -> None:
    replied_msg = message.reply_to_message
    if not replied_msg:
        return

    new_meaning = (message.text or "").strip()
    if not new_meaning:
        await message.reply("Please enter a valid meaning.")
        return

    await arq.delete(state_key)
    with contextlib.suppress(Exception):
        await message.delete()

    settings = get_settings()
    async with httpx.AsyncClient() as http:
        client = AnkiConnect(settings.ankiconnect_url, http)
        q = build_find_query(settings.note_type, word_field)
        note_ids = await client.find_notes(q)
        if note_ids:
            await client.update_note_fields(note_ids[0], {FIELD_SI_MEANING: new_meaning})
            await client.sync()

    results_key = f"batch_results:{replied_msg.message_id}"
    results_bytes = await arq.get(results_key)
    if results_bytes:
        rb = results_bytes
        results = json.loads(rb.decode() if isinstance(rb, bytes) else rb)
        for r in results:
            if r.get("word") == word_field:
                r["si_meaning"] = new_meaning
                break
        await arq.set(results_key, json.dumps(results), ex=86400)

        preview_text = safe_markdown(render_card_preview(results))
        kb = completed_keyboard(results)
        try:
            await replied_msg.edit_text(
                text=preview_text,
                parse_mode="MarkdownV2",
                reply_markup=kb,
            )
        except Exception as e:
            log.error("edit_reply.edit_original.failed", error=str(e))
    else:
        await replied_msg.edit_text(
            text=f"✅ Meaning updated in Anki for `{word_field.split(':', 1)[-1]}`."
        )


async def _monitor_regen(
    status_msg: Message,
    job: Job,
    word_field: str,
    original_message_id: int,
    arq: ArqRedis,
    bot: Bot,
) -> None:
    from arq.jobs import JobStatus

    headword = word_field.split(":", 1)[-1]
    progress_key = f"progress:{job.job_id}:{headword}"

    last_text = ""
    while True:
        try:
            js = await job.status()
            if js not in (JobStatus.queued, JobStatus.in_progress):
                break
        except Exception:
            break

        try:
            val = await arq.get(progress_key)
            state = val.decode() if isinstance(val, bytes) else (val or "queue")
        except Exception:
            state = "queue"

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

        formatted = format_state(state)
        text = f"⏳ **Regenerating examples for `{headword}`...**\n\nStatus: {formatted}"
        summary_text = safe_markdown(text)

        if summary_text != last_text:
            try:
                await bot.edit_message_text(
                    text=summary_text,
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id,
                    parse_mode="MarkdownV2",
                )
                last_text = summary_text
            except Exception:
                pass

        await asyncio.sleep(1.5)

    job_res = None
    try:
        job_res = await job.result()
    except Exception as e:
        log.error("regen.job.failed", error=str(e))

    results_key = f"batch_results:{original_message_id}"
    results_bytes = await arq.get(results_key)
    if results_bytes:
        rb = results_bytes
        results = json.loads(rb.decode() if isinstance(rb, bytes) else rb)
        updated = False
        if job_res:
            for r in job_res:
                if r.get("outcome") in ("added", "rewritten"):
                    for idx, item in enumerate(results):
                        if item.get("word") == word_field:
                            results[idx] = r
                            updated = True
                            break

        if updated:
            await arq.set(results_key, json.dumps(results), ex=86400)

        preview_text = safe_markdown(render_card_preview(results))
        kb = completed_keyboard(results)
        try:
            await bot.edit_message_text(
                text=preview_text,
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                parse_mode="MarkdownV2",
                reply_markup=kb,
            )
        except Exception as e:
            log.error("regen.final_edit.failed", error=str(e))
    else:
        await status_msg.edit_text(f"✅ Regeneration completed for `{headword}`.")


@router.callback_query(F.data.startswith("regen_examples:"))
async def on_regen_examples(query: CallbackQuery, arq: ArqRedis, bot: Bot) -> None:
    if not query.data:
        return
    await query.answer()
    word_field = query.data.split(":", 1)[1]
    headword = word_field.split(":", 1)[-1]

    if not isinstance(query.message, Message):
        return

    text = safe_markdown(f"⏳ **Regenerating examples for `{headword}`...**")
    await query.message.edit_text(text=text, parse_mode="MarkdownV2", reply_markup=None)

    import time

    from lexibot.worker.enqueue import normalize_word_key

    user_id = query.from_user.id
    jid = f"w:{user_id}:{normalize_word_key(headword)}:regen:{int(time.time())}"

    progress_key = f"progress:{jid}:{headword}"
    await arq.set(progress_key, "queue", ex=3600)

    job = await arq.enqueue_job(
        "process_chunk",
        [{"headword": headword}],
        user_id,
        _job_id=jid,
    )
    if job is None:
        job = Job(jid, arq)

    task = asyncio.create_task(
        _monitor_regen(query.message, job, word_field, query.message.message_id, arq, bot)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
