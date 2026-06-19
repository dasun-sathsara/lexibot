"""Typed error hierarchy.

Handlers ``match`` on these types to produce friendly, actionable user-facing copy.
"""

from __future__ import annotations


class LexibotError(Exception):
    """Base class for all domain errors."""


class LLMError(LexibotError):
    """The language model failed (validation, exhausted retries, etc.)."""


class TTSError(LexibotError):
    """Speech synthesis failed."""


class AnkiError(LexibotError):
    """An AnkiConnect call returned an error payload."""


class AnkiUnavailable(AnkiError):
    """AnkiConnect could not be reached (connection refused / Anki down).

    Triggers offline queueing: the item is re-queued and the user is told it is saved.
    """


class InvalidWord(LexibotError):
    """The LLM determined the input is not a valid word; the item is skipped."""
