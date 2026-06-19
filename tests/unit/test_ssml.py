"""SSML-01 .. SSML-07 — SSML builder.

SSML-05/06 are regression-drivers: the architecture sketch omits XML escaping, so a word
like ``rock & roll`` or text with a quote would produce invalid SSML and a 400 from Azure.
These tests force the hardened (escaping) implementation.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from lexibot.tts.ssml import build_ssml


def test_ssml_01_slow_rate() -> None:
    assert 'rate="-15%"' in build_ssml("run", gender="female", slow=True)


def test_ssml_02_normal_rate() -> None:
    assert 'rate="0%"' in build_ssml("run", gender="female", slow=False)


def test_ssml_03_female_voice() -> None:
    assert "en-US-Harper:MAI-Voice-2" in build_ssml("run", gender="female", slow=False)


def test_ssml_04_male_voice() -> None:
    assert "en-US-Ethan:MAI-Voice-2" in build_ssml("run", gender="male", slow=False)


def test_ssml_05_escapes_special_chars() -> None:
    out = build_ssml('rock & "roll" <x>', gender="female", slow=False)
    assert "&amp;" in out
    assert "&lt;" in out
    assert "&quot;" in out or "&#34;" in out
    ET.fromstring(out)  # must remain well-formed


def test_ssml_06_well_formed_xml() -> None:
    out = build_ssml("she said 'hi' & left <abruptly>", gender="male", slow=True)
    # Parses without raising.
    ET.fromstring(out)


def test_ssml_07_unknown_gender() -> None:
    with pytest.raises((KeyError, ValueError)):
        build_ssml("x", gender="robot", slow=False)
