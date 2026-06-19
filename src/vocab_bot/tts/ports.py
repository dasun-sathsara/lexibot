"""TTS port (Protocol)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Synthesizer(Protocol):
    async def synthesize(self, text: str, *, slow: bool = False) -> bytes: ...
