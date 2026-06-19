"""Shared fixtures.

Only fixtures used by the pure-logic suite are wired live; the dependency-mocking fixtures
(fake_connect / fake_tts / fake_llm / respx_mock) are intentionally omitted because those
adapter/pipeline tests are out of scope for this build.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from lexibot.core.enums import PartOfSpeech
from lexibot.core.models import Card, RawItem, Sense


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """Monkeypatched ``time.monotonic`` for the key-pool timing tests (KEY-*)."""
    t = {"now": 1000.0}
    monkeypatch.setattr("lexibot.llm.keypool.time.monotonic", lambda: t["now"])
    return t


@pytest.fixture
def make_sense() -> Callable[..., Sense]:
    def _make(
        headword: str = "run",
        *,
        part_of_speech: PartOfSpeech = PartOfSpeech.VERB,
        is_valid_word: bool = True,
        en_meaning: str = "to move quickly on foot",
        si_meaning: str = "diwanawa",
        sentence_1: str = "I run every morning.",
        sentence_2: str = "She runs to school.",
    ) -> Sense:
        return Sense(
            headword=headword,
            part_of_speech=part_of_speech,
            is_valid_word=is_valid_word,
            en_meaning=en_meaning,
            si_meaning=si_meaning,
            sentence_1=sentence_1,
            sentence_2=sentence_2,
        )

    return _make


@pytest.fixture
def sample_card(make_sense: Callable[..., Sense]) -> Card:
    return Card.from_sense(make_sense(), audio=(b"w", b"e1", b"e2"), gender="female")


@pytest.fixture
def make_card(make_sense: Callable[..., Sense]) -> Callable[..., Card]:
    def _make(word_field: str = "v:run") -> Card:
        pos, _, head = word_field.partition(":")
        sense = make_sense(headword=head, part_of_speech=PartOfSpeech(pos))
        return Card.from_sense(sense, audio=(b"w", b"e1", b"e2"), gender="female")

    return _make


@pytest.fixture
def make_items() -> Callable[[int], list[RawItem]]:
    def _make(n: int) -> list[RawItem]:
        return [RawItem(headword=f"word{i}") for i in range(n)]

    return _make


@pytest.fixture
def sleep_spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """Records ``asyncio.sleep`` durations without actually waiting."""
    import asyncio

    recorded: list[float] = []
    real_sleep = asyncio.sleep

    async def _spy(delay: float, *args: object, **kwargs: object) -> None:
        recorded.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _spy)
    yield recorded
