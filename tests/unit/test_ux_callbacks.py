"""UX callback rendering, completed_keyboard layout, and is_edit_reply state helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import InlineKeyboardMarkup, Message, User

from lexibot.bot.handlers.callbacks import is_edit_reply
from lexibot.bot.keyboards import completed_keyboard
from lexibot.bot.rendering import render_card_preview
from lexibot.core.runner import StateStore


def test_render_card_preview_single() -> None:
    results = [
        {
            "word": "n:reprimand",
            "outcome": "added",
            "headword": "reprimand",
            "pos": "n",
            "si_meaning": "meaning1",
            "en_meaning": "definition1",
            "sentence_1": "sentence1",
            "sentence_2": "sentence2",
        }
    ]
    preview = render_card_preview(results)
    assert "Batch Processing Complete" in preview
    assert "1. reprimand" in preview
    assert "Meaning" in preview
    assert "meaning1" in preview
    assert "Definition" in preview
    assert "definition1" in preview
    assert "sentence1" in preview
    assert "sentence2" in preview


def test_render_card_preview_multiple() -> None:
    results = [
        {
            "word": "n:reprimand",
            "outcome": "added",
            "headword": "reprimand",
            "pos": "n",
            "si_meaning": "meaning1",
            "en_meaning": "definition1",
            "sentence_1": "sentence1",
            "sentence_2": "sentence2",
        },
        {
            "word": "v:dejavu",
            "outcome": "rewritten",
            "headword": "dejavu",
            "pos": "v",
            "si_meaning": "meaning2",
            "en_meaning": "definition2",
            "sentence_1": "sentence2_1",
            "sentence_2": "",
        },
    ]
    preview = render_card_preview(results)
    assert "1. reprimand" in preview
    assert "2. dejavu" in preview
    assert "sentence2_1" in preview
    assert "meaning2" in preview


def test_render_card_preview_all_failed() -> None:
    results = [
        {
            "word": "repremend",
            "outcome": "skipped",
            "error": "LLM enrichment failed",
        }
    ]
    preview = render_card_preview(results)
    assert "Batch Processing Failed" in preview
    assert "repremend" in preview
    assert "LLM enrichment failed" in preview


def test_completed_keyboard_single() -> None:
    results = [
        {
            "word": "n:reprimand",
            "outcome": "added",
            "headword": "reprimand",
        }
    ]
    kb = completed_keyboard(results)
    assert isinstance(kb, InlineKeyboardMarkup)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 3
    assert buttons[0].text == "✏️ Edit Meaning"
    assert buttons[0].callback_data == "edit_meaning:n:reprimand"
    assert buttons[1].text == "🔄 Regen Examples"
    assert buttons[1].callback_data == "regen_examples:n:reprimand"
    assert buttons[2].text == "🗑️ Delete Card"
    assert buttons[2].callback_data == "delete_card:n:reprimand"


def test_completed_keyboard_multiple() -> None:
    results = [
        {
            "word": "n:reprimand",
            "outcome": "added",
            "headword": "reprimand",
        },
        {
            "word": "v:dejavu",
            "outcome": "rewritten",
            "headword": "dejavu",
        },
    ]
    kb = completed_keyboard(results)
    assert isinstance(kb, InlineKeyboardMarkup)
    rows = kb.inline_keyboard
    assert len(rows) == 2
    row0 = rows[0]
    assert len(row0) == 3
    assert row0[0].text == "✏️ Edit (reprimand)"
    assert row0[0].callback_data == "edit_meaning:n:reprimand"
    assert row0[1].text == "🔄 Regen (reprimand)"
    assert row0[1].callback_data == "regen_examples:n:reprimand"
    assert row0[2].text == "🗑️ Delete (reprimand)"
    assert row0[2].callback_data == "delete_card:n:reprimand"


@pytest.mark.asyncio
async def test_is_edit_reply_no_reply() -> None:
    msg = MagicMock(spec=Message)
    msg.reply_to_message = None
    state = AsyncMock(spec=StateStore)
    res = await is_edit_reply(msg, state)
    assert res is False


@pytest.mark.asyncio
async def test_is_edit_reply_not_in_redis() -> None:
    msg = MagicMock(spec=Message)
    replied = MagicMock(spec=Message)
    replied.message_id = 123
    msg.reply_to_message = replied
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = 456
    state = MagicMock()
    state.get = AsyncMock(return_value=None)
    res = await is_edit_reply(msg, state)
    assert res is False
    state.get.assert_called_once_with("edit_state:456:123")


@pytest.mark.asyncio
async def test_is_edit_reply_success() -> None:
    msg = MagicMock(spec=Message)
    replied = MagicMock(spec=Message)
    replied.message_id = 123
    msg.reply_to_message = replied
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = 456
    state = MagicMock()
    state.get = AsyncMock(return_value=b"n:reprimand")
    res = await is_edit_reply(msg, state)
    assert res == {"word_field": "n:reprimand", "state_key": "edit_state:456:123"}
