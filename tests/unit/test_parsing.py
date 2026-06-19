"""PARSE-01 .. PARSE-14 — message parsing contract."""

from __future__ import annotations

import pytest

from vocab_bot.core.parsing import parse_message


def _pairs(raw: str) -> list[tuple[str, str | None]]:
    return [(i.headword, i.sense_hint) for i in parse_message(raw)]


def test_parse_01_single_word() -> None:
    assert _pairs("run") == [("run", None)]


def test_parse_02_comma_separated() -> None:
    assert _pairs("run, jump, swim") == [("run", None), ("jump", None), ("swim", None)]


def test_parse_03_newline_separated() -> None:
    assert _pairs("run\njump\nswim") == [("run", None), ("jump", None), ("swim", None)]


def test_parse_04_word_plus_meaning_colon() -> None:
    assert _pairs("bank: the financial institution") == [("bank", "the financial institution")]


def test_parse_05_word_plus_meaning_hyphen() -> None:
    assert _pairs("bank - the side of a river") == [("bank", "the side of a river")]


def test_parse_06_phrase_not_split() -> None:
    assert _pairs("break the ice") == [("break the ice", None)]


def test_parse_07_phrases_preserved_across_commas() -> None:
    assert _pairs("make up, run into") == [("make up", None), ("run into", None)]


def test_parse_08_hyphenated_word_not_split() -> None:
    assert _pairs("well-being") == [("well-being", None)]


def test_parse_09_split_on_first_delimiter_only() -> None:
    assert _pairs("spring - the season - not the coil") == [("spring", "the season - not the coil")]


def test_parse_10_trim_and_drop_empties() -> None:
    assert _pairs("run  ,  ,  jump") == [("run", None), ("jump", None)]


def test_parse_11_empty_hint_normalized_to_none() -> None:
    assert _pairs("bank:") == [("bank", None)]


def test_parse_12_empty_message() -> None:
    assert _pairs("") == []
    assert _pairs("   \n  \t ") == []


def test_parse_13_mixed_lines_and_commas() -> None:
    assert _pairs("run, bank: money\nswim") == [
        ("run", None),
        ("bank", "money"),
        ("swim", None),
    ]


def test_parse_14_strip_surrounding_markdown() -> None:
    assert _pairs("**run**") == [("run", None)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("run", [("run", None)]),
        ("run, jump, swim", [("run", None), ("jump", None), ("swim", None)]),
        ("bank: the financial institution", [("bank", "the financial institution")]),
        ("break the ice", [("break the ice", None)]),
        ("make up, run into", [("make up", None), ("run into", None)]),
        ("well-being", [("well-being", None)]),
        ("spring - the season - not the coil", [("spring", "the season - not the coil")]),
        ("  run  ,  ,  jump  ", [("run", None), ("jump", None)]),
        ("", []),
    ],
)
def test_parse_message_table(raw: str, expected: list[tuple[str, str | None]]) -> None:
    assert _pairs(raw) == expected
