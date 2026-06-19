"""Domain enums shared across the pipeline."""

from __future__ import annotations

from enum import StrEnum


class PartOfSpeech(StrEnum):
    """Part-of-speech short codes used in the ``Word`` field (``<pos>:<headword>``)."""

    NOUN = "n"
    VERB = "v"
    ADJECTIVE = "adj"
    ADVERB = "adv"
    PREPOSITION = "prep"
    CONJUNCTION = "conj"
    PRONOUN = "pron"
    PHRASE = "phr"


class ItemOutcome(StrEnum):
    """Result of processing a single vocabulary item."""

    ADDED = "added"
    REWRITTEN = "rewritten"
    SKIPPED = "skipped"
