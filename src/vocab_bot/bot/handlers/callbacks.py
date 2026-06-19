"""Preview callback handlers: Add / Regenerate / Fix sense / Discard."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from vocab_bot.bot.keyboards import CB_ADD, CB_DISCARD, CB_FIX, CB_REGEN

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
