"""Inline keyboards for the single-word preview."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Callback action prefixes. Payload format: ``<action>:<token>``.
CB_ADD = "add"
CB_REGEN = "regen"
CB_FIX = "fix"
CB_DISCARD = "discard"


def preview_keyboard(token: str) -> InlineKeyboardMarkup:
    """Buttons for a single-word preview: Add / Regenerate / Fix sense / Discard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="\u2705 Add", callback_data=f"{CB_ADD}:{token}"),
        InlineKeyboardButton(text="\U0001f504 Regenerate", callback_data=f"{CB_REGEN}:{token}"),
    )
    builder.row(
        InlineKeyboardButton(text="\u270f\ufe0f Fix sense", callback_data=f"{CB_FIX}:{token}"),
        InlineKeyboardButton(text="\u274c Discard", callback_data=f"{CB_DISCARD}:{token}"),
    )
    return builder.as_markup()
