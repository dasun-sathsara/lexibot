"""Inline keyboards for word preview and completed-word actions."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from lexibot.core.enums import ItemOutcome

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


def completed_keyboard(results: list[dict[str, str]]) -> InlineKeyboardMarkup | None:
    """Inline keyboard for completed words.

    Includes Edit Meaning, Regen Examples, and Delete Card buttons.
    Returns ``None`` when no words were added or rewritten.
    """
    completed = [
        r for r in results if r.get("outcome") in (ItemOutcome.ADDED, ItemOutcome.REWRITTEN)
    ]
    if not completed:
        return None

    builder = InlineKeyboardBuilder()
    if len(completed) == 1:
        item = completed[0]
        wf = item["word"]
        builder.row(
            InlineKeyboardButton(text="✏️ Edit Meaning", callback_data=f"edit_meaning:{wf}"),
            InlineKeyboardButton(text="🔄 Regen Examples", callback_data=f"regen_examples:{wf}"),
        )
        builder.row(
            InlineKeyboardButton(text="🗑️ Delete Card", callback_data=f"delete_card:{wf}"),
        )
    else:
        for item in completed:
            wf = item["word"]
            hw = item.get("headword", wf.split(":", 1)[-1])
            builder.row(
                InlineKeyboardButton(text=f"✏️ Edit ({hw})", callback_data=f"edit_meaning:{wf}"),
                InlineKeyboardButton(text=f"🔄 Regen ({hw})", callback_data=f"regen_examples:{wf}"),
                InlineKeyboardButton(text=f"🗑️ Delete ({hw})", callback_data=f"delete_card:{wf}"),
            )
    return builder.as_markup()
