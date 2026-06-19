"""SSML builder for MAI-Voice-2.

Hardened against the architecture sketch: all dynamic text is XML-escaped so words/sentences
containing ``& < > " '`` produce well-formed SSML rather than a 400 from Azure (SSML-05/06).
The word is synthesized ~15% slower for clarity; sentences run at normal rate.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

# en-US MAI-Voice-2 voices.
VOICES: dict[str, str] = {
    "female": "en-US-Harper:MAI-Voice-2",
    "male": "en-US-Ethan:MAI-Voice-2",
}


def voice_for(gender: str) -> str:
    """Return the voice name for ``gender`` or raise ``KeyError`` (no silent default)."""
    return VOICES[gender]


def build_ssml(text: str, *, gender: str, slow: bool) -> str:
    """Build a well-formed SSML document for one utterance.

    All special characters in ``text`` and the voice name are XML-escaped.
    """
    rate = "-15%" if slow else "0%"
    voice = voice_for(gender)
    # escape() handles & < >; the entity map adds " and ' so the test's &quot; holds and
    # the text is safe in any XML position.
    safe_text = escape(text, {'"': "&quot;", "'": "&apos;"})
    voice_attr = quoteattr(voice)
    rate_attr = quoteattr(rate)
    return (
        '<speak version="1.0" xml:lang="en-US">'
        f"<voice name={voice_attr}>"
        f"<prosody rate={rate_attr}>{safe_text}</prosody>"
        "</voice></speak>"
    )
