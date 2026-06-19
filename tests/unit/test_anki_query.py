"""Pure-logic Anki tests: query escaping + media naming.

Covers the testable cores of UPSERT-04 (quote escaping), UPSERT-06/07 (media filename
stability + voice cache-busting), and UPSERT-08 (collection-wide query). The decision-path
cases (UPSERT-01/02/03/05) require mocking the AnkiConnect client and are out of scope.
"""

from __future__ import annotations

from vocab_bot.anki.connect import build_find_query, escape_query_term
from vocab_bot.core.models import media_filename


def test_upsert_04_escapes_double_quote_in_term() -> None:
    assert escape_query_term('say "hi"') == r"say \"hi\""


def test_upsert_04_query_escapes_quote_no_injection() -> None:
    query = build_find_query("Eng Vocab 2 Examples", 'n:say "hi"')
    # The embedded quote is escaped inside the search term.
    assert r"\"hi\"" in query
    # The escaped quote must not appear unescaped (which would close the term early).
    assert 'say "hi"' not in query


def test_escape_handles_backslash_before_quote() -> None:
    # Backslash escaped first, then the quote, so order is well-defined.
    assert escape_query_term(r"a\"b") == r"a\\\"b"


def test_upsert_08_query_is_collection_wide() -> None:
    query = build_find_query("Eng Vocab 2 Examples", "v:run")
    assert "deck:" not in query
    assert '"note:Eng Vocab 2 Examples"' in query
    assert '"Word:v:run"' in query


def test_upsert_06_media_filename_stable_for_same_text_voice() -> None:
    a = media_filename("run", "run", gender="female")
    b = media_filename("run", "run", gender="female")
    assert a == b
    assert a.startswith("tgb_run_")
    assert a.endswith(".mp3")


def test_upsert_06_media_suffixes() -> None:
    ex1 = media_filename("run", "I run.", gender="female", suffix="ex1")
    ex2 = media_filename("run", "She runs.", gender="female", suffix="ex2")
    assert ex1.endswith("_ex1.mp3")
    assert ex2.endswith("_ex2.mp3")


def test_upsert_07_media_hash_busts_on_voice_change() -> None:
    female = media_filename("run", "run", gender="female")
    male = media_filename("run", "run", gender="male")
    assert female != male
