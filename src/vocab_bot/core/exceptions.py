"""Typed error hierarchy (architecture §10).

Handlers ``match`` on these types to produce friendly, actionable user-facing copy.
"""

from __future__ import annotations


class VocabBotError(Exception):
    """Base class for all domain errors."""


class LLMError(VocabBotError):
    """The language model failed (validation, exhausted retries, etc.)."""


class TTSError(VocabBotError):
    """Speech synthesis failed."""


class AnkiError(VocabBotError):
    """An AnkiConnect call returned an error payload."""


class AnkiUnavailable(AnkiError):
    """AnkiConnect could not be reached (connection refused / Anki down).

    Triggers offline queueing: the item is re-queued and the user is told it is saved.
    """


class InvalidWord(VocabBotError):
    """The LLM determined the input is not a valid word; the item is skipped."""
