"""Immutable pydantic domain models.

The models form the boundary between the parsing layer, the LLM/TTS adapters, and the
Anki write path. ``Sense`` is the Gemini structured-output shape; ``Card`` is the fully
assembled note (fields + media) ready for the upsert.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

from lexibot.core.enums import PartOfSpeech

# Anki note-type field names.
FIELD_WORD = "Word"
FIELD_WORD_PRON = "Word Pronunciation"
FIELD_EN_MEANING = "English Meaning"
FIELD_SENTENCE_1 = "Example Sentence 1"
FIELD_SENTENCE_PRON_1 = "Example Sentence Pronunciation 1"
FIELD_SENTENCE_2 = "Example Sentence 2"
FIELD_SENTENCE_PRON_2 = "Example Sentence Pronunciation 2"
FIELD_SI_MEANING = "Sinhala Meaning"

# Media filename namespace, kept distinct from his existing ``nn_`` media.
MEDIA_PREFIX = "tgb"
_HASH_LEN = 8


class RawItem(BaseModel):
    """A single candidate item parsed from an inbound message.

    ``headword`` is the raw text as typed (LLM normalization happens later). ``sense_hint``
    carries the disambiguating meaning when the user used a ``word - meaning`` form.
    """

    model_config = ConfigDict(frozen=True)

    headword: str
    sense_hint: str | None = None


class Sense(BaseModel):
    """Gemini structured-output result for one word."""

    model_config = ConfigDict(frozen=True)

    headword: str
    part_of_speech: PartOfSpeech
    is_valid_word: bool
    en_meaning: str
    si_meaning: str
    sentence_1: str
    sentence_2: str

    @property
    def word_field(self) -> str:
        """The ``Word`` field value, e.g. ``adj:artificial``."""
        return f"{self.part_of_speech}:{self.headword}"


def media_filename(headword: str, text: str, *, gender: str, suffix: str = "") -> str:
    """Build a namespaced media filename.

    The hash covers the spoken ``text`` plus the ``gender`` (voice), so the same word in a
    different voice produces a different filename (UPSERT-07 cache-busting), while the same
    text+voice is stable (UPSERT-06).

    :param headword: Used to build the human-readable slug in the filename.
    :param text: The spoken text whose bytes are hashed.
    :param gender: Voice identity, mixed into the hash for cache-busting.
    :param suffix: Optional extra label (e.g. "ex1") inserted before ``.mp3``.
    """
    digest = hashlib.sha256(f"{text}\x00{gender}".encode()).hexdigest()[:_HASH_LEN]
    slug = "".join(c if c.isalnum() else "_" for c in headword.strip().lower())
    tail = f"_{suffix}" if suffix else ""
    return f"{MEDIA_PREFIX}_{slug}_{digest}{tail}.mp3"


class MediaClip(BaseModel):
    """One audio clip destined for an Anki media file + a pronunciation field."""

    model_config = ConfigDict(frozen=True)

    filename: str
    field: str
    audio: bytes

    @property
    def sound_tag(self) -> str:
        """The ``[sound:...]`` reference inserted into the pronunciation field."""
        return f"[sound:{self.filename}]"


class Card(BaseModel):
    """A fully-assembled Anki note: typed fields plus up to three media clips."""

    model_config = ConfigDict(frozen=True)

    word_field: str
    en_meaning: str
    si_meaning: str
    sentence_1: str
    sentence_2: str
    media: tuple[MediaClip, ...] = ()

    @classmethod
    def from_sense(
        cls,
        sense: Sense,
        *,
        audio: tuple[bytes | None, bytes | None, bytes | None] | None = None,
        gender: str = "female",
    ) -> Card:
        """Assemble a card from a ``Sense`` and (optionally) its three audio clips.

        ``audio`` is ``(word, sentence_1, sentence_2)``. ``None`` for a clip means that
        clip failed; the others are still stored so partial TTS progress is preserved.
        When ``audio`` itself is ``None`` no media is attached.

        :param gender: Voice identity forwarded to ``media_filename``.
        """
        clips: list[MediaClip] = []
        if audio is not None:
            word_audio, ex1_audio, ex2_audio = audio
            if word_audio is not None:
                clips.append(
                    MediaClip(
                        filename=media_filename(sense.headword, sense.headword, gender=gender),
                        field=FIELD_WORD_PRON,
                        audio=word_audio,
                    )
                )
            if ex1_audio is not None:
                clips.append(
                    MediaClip(
                        filename=media_filename(
                            sense.headword, sense.sentence_1, gender=gender, suffix="ex1"
                        ),
                        field=FIELD_SENTENCE_PRON_1,
                        audio=ex1_audio,
                    )
                )
            if ex2_audio is not None:
                clips.append(
                    MediaClip(
                        filename=media_filename(
                            sense.headword, sense.sentence_2, gender=gender, suffix="ex2"
                        ),
                        field=FIELD_SENTENCE_PRON_2,
                        audio=ex2_audio,
                    )
                )
        return cls(
            word_field=sense.word_field,
            en_meaning=sense.en_meaning,
            si_meaning=sense.si_meaning,
            sentence_1=sense.sentence_1,
            sentence_2=sense.sentence_2,
            media=tuple(clips),
        )

    @property
    def fields(self) -> dict[str, str]:
        """The AnkiConnect ``fields`` mapping.

        Pronunciation fields carry the ``[sound:...]`` tag for whichever clips exist; when a
        clip is missing its field is left empty so audio can be backfilled on retry.
        """
        sounds = {clip.field: clip.sound_tag for clip in self.media}
        return {
            FIELD_WORD: self.word_field,
            FIELD_WORD_PRON: sounds.get(FIELD_WORD_PRON, ""),
            FIELD_EN_MEANING: self.en_meaning,
            FIELD_SENTENCE_1: self.sentence_1,
            FIELD_SENTENCE_PRON_1: sounds.get(FIELD_SENTENCE_PRON_1, ""),
            FIELD_SENTENCE_2: self.sentence_2,
            FIELD_SENTENCE_PRON_2: sounds.get(FIELD_SENTENCE_PRON_2, ""),
            FIELD_SI_MEANING: self.si_meaning,
        }
