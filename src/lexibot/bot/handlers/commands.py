"""Command handlers: /start, /model, /help."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="commands")

_HELP = (
    "Send me English words and I'll build Anki cards with Sinhala + English meanings, two "
    "example sentences, and audio.\n\n"
    "\u2022 One word, a comma/newline list, or `word - meaning` to target a sense.\n"
    "\u2022 /model flash|pro \u2014 choose the Gemini model.\n"
    "\u2022 /help \u2014 show this message."
)


@router.message(CommandStart())
async def start(message: Message) -> None:
    user = message.from_user
    uid = user.id if user else "unknown"
    await message.answer(
        f"\U0001f44b Your Telegram ID is `{uid}`.\n\n{_HELP}",
    )


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(_HELP)


@router.message(Command("model"))
async def model_cmd(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip().lower() not in {"flash", "pro"}:
        await message.answer("Usage: /model flash|pro")
        return
    choice = parts[1].strip().lower()
    model = "gemini-3.5-flash" if choice == "flash" else "gemini-3.1-pro-preview"
    await message.answer(f"Model set to `{model}` for your next words.")
