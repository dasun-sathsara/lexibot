"""Prompt construction for the enrichment call."""

from __future__ import annotations

from vocab_bot.core.models import RawItem

SYSTEM_INSTRUCTION = (
    "You are a lexicographer building Anki flashcards for a Sinhala-speaking English "
    "learner (CEFR A2-B1). For each input item produce: the normalized English headword "
    "(silently correcting typos to the intended word), its part of speech, an English "
    "meaning, a Sinhala meaning, and two natural example sentences at A2-B1 difficulty. "
    "If an item is not a real English word or phrase, set is_valid_word to false and leave "
    "the other text fields empty. When a sense hint is given, target that exact sense and "
    "let the part of speech follow that sense. Return one result per input item, in order."
)


def _format_item(item: RawItem) -> str:
    if item.sense_hint:
        return f"- {item.headword} (intended sense: {item.sense_hint})"
    return f"- {item.headword}"


def build_user_prompt(items: list[RawItem]) -> str:
    """Render the chunk of items into a single user prompt."""
    lines = [_format_item(item) for item in items]
    return "Enrich the following items:\n" + "\n".join(lines)
