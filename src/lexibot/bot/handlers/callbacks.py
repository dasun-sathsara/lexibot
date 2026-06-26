"""Callback handlers: preview actions (add/regen/fix/discard) and card management
(delete/edit/regen examples)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from lexibot.anki.connect import AnkiConnect, build_find_query
from lexibot.bot.keyboards import CB_ADD, CB_DISCARD, CB_FIX, CB_REGEN, completed_keyboard
from lexibot.bot.rendering import render_card_preview, safe_markdown
from lexibot.bot.task_registry import spawn_task
from lexibot.config import get_settings
from lexibot.core.enums import ItemOutcome
from lexibot.core.models import FIELD_SI_MEANING, RawItem
from lexibot.core.runner import BatchProgress, PipelineRunner, StateStore

log = structlog.get_logger(__name__)

router = Router(name="callbacks")


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
        text = safe_markdown(f"\U0001f5d1\ufe0f **Deleted**: `{headword}`")
        await query.message.edit_text(text=text, parse_mode="MarkdownV2", reply_markup=None)


@router.callback_query(F.data.startswith("edit_meaning:"))
async def on_edit_meaning(query: CallbackQuery, state: StateStore) -> None:
    if not query.data:
        return
    await query.answer()
    word_field = query.data.split(":", 1)[1]
    headword = word_field.split(":", 1)[-1]

    if not isinstance(query.message, Message):
        return

    user_id = query.from_user.id
    message_id = query.message.message_id

    await state.set(f"edit_state:{user_id}:{message_id}", word_field, ex=600)

    msg = f"\u270f\ufe0f **Edit Meaning**: Reply to this message with the new Sinhala meaning for `{headword}`"
    text = safe_markdown(msg)
    await query.message.edit_text(text=text, parse_mode="MarkdownV2", reply_markup=None)


async def is_edit_reply(message: Message, state: StateStore) -> bool | dict[str, Any]:
    if not message.reply_to_message:
        return False
    user = message.from_user
    if not user:
        return False
    state_key = f"edit_state:{user.id}:{message.reply_to_message.message_id}"
    word_field_bytes = await state.get(state_key)
    if not word_field_bytes:
        return False
    wb = word_field_bytes
    word_field = wb.decode() if isinstance(wb, bytes) else wb
    return {"word_field": word_field, "state_key": state_key}


@router.message(is_edit_reply)
async def on_edit_reply(
    message: Message,
    state: StateStore,
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

    await state.delete(state_key)
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
    results_bytes = await state.get(results_key)
    if results_bytes:
        rb = results_bytes
        results = json.loads(rb.decode() if isinstance(rb, bytes) else rb)
        for r in results:
            if r.get("word") == word_field:
                r["si_meaning"] = new_meaning
                break
        await state.set(results_key, json.dumps(results), ex=86400)

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
            text=f"\u2705 Meaning updated in Anki for `{word_field.split(':', 1)[-1]}`."
        )


async def _monitor_regen(
    status_msg: Message,
    handle: BatchProgress,
    word_field: str,
    original_message_id: int,
    state: StateStore,
    bot: Bot,
) -> None:
    """Poll the in-memory BatchProgress for a single-word regen and edit the status message."""
    headword = word_field.split(":", 1)[-1]

    last_text = ""
    while not handle.done.is_set():
        target = headword.strip().casefold()
        state_val = handle.states.get(target, "queue")

        formatted = _format_regen_state(state_val)
        text = f"\u23f3 **Regenerating examples for `{headword}`...**\n\nStatus: {formatted}"
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

    job_res = handle.results

    results_key = f"batch_results:{original_message_id}"
    results_bytes = await state.get(results_key)
    if results_bytes:
        rb = results_bytes
        results = json.loads(rb.decode() if isinstance(rb, bytes) else rb)
        updated = False
        if job_res:
            for r in job_res:
                if r.get("outcome") in (ItemOutcome.ADDED, ItemOutcome.REWRITTEN):
                    for idx, item in enumerate(results):
                        if item.get("word") == word_field:
                            results[idx] = r
                            updated = True
                            break

        if updated:
            await state.set(results_key, json.dumps(results), ex=86400)

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
        await status_msg.edit_text(f"\u2705 Regeneration completed for `{headword}`.")


def _format_regen_state(state: str) -> str:
    """Render one headword's pipeline step for the regen stepper (mirrors words.py)."""
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


@router.callback_query(F.data.startswith("regen_examples:"))
async def on_regen_examples(
    query: CallbackQuery, runner: PipelineRunner, state: StateStore, bot: Bot
) -> None:
    if not query.data:
        return
    await query.answer()
    word_field = query.data.split(":", 1)[1]
    headword = word_field.split(":", 1)[-1]

    if not isinstance(query.message, Message):
        return

    text = safe_markdown(f"\u23f3 **Regenerating examples for `{headword}`...**")
    await query.message.edit_text(text=text, parse_mode="MarkdownV2", reply_markup=None)

    user_id = query.from_user.id
    # submit_chunk keys off job_id(user_id, headword); a regen of the same word
    # while one is in-flight coalesces (returns the same handle).
    # TODO(review): append a timestamped namespace to job_id for distinct concurrent regens.
    items = [RawItem(headword=headword)]
    _jid, handle = runner.submit_chunk(user_id=user_id, items=items)

    spawn_task(
        _monitor_regen(query.message, handle, word_field, query.message.message_id, state, bot)
    )
