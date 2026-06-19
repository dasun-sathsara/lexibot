"""Gemini structured-output schema (architecture §6/§7, plan §7).

A single call returns an array of these objects (one per word in the chunk). The response
model mirrors :class:`vocab_bot.core.models.Sense` but is kept separate so the wire schema can
evolve independently of the domain model.
"""

from __future__ import annotations

from pydantic import BaseModel

from vocab_bot.core.enums import PartOfSpeech
from vocab_bot.core.models import Sense


class SenseOut(BaseModel):
    """One enriched word as returned by the model."""

    headword: str
    part_of_speech: PartOfSpeech
    is_valid_word: bool
    en_meaning: str
    si_meaning: str
    sentence_1: str
    sentence_2: str

    def to_sense(self) -> Sense:
        return Sense(
            headword=self.headword,
            part_of_speech=self.part_of_speech,
            is_valid_word=self.is_valid_word,
            en_meaning=self.en_meaning,
            si_meaning=self.si_meaning,
            sentence_1=self.sentence_1,
            sentence_2=self.sentence_2,
        )


class ChunkResponse(BaseModel):
    """Top-level structured response for a chunk of words."""

    items: list[SenseOut]
