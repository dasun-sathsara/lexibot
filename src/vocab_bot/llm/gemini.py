"""Gemini language-model adapter (architecture §7, plan §7).

Uses the unified Google Gen AI SDK (``google-genai``) with Pydantic structured output. A
key is drawn from the :class:`GeminiKeyPool` per call; on an HTTP 429 the key is penalized
and the call is retried (RETRY-01), with bounded attempts before surfacing ``LLMError``
(RETRY-02/05).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from vocab_bot.core.exceptions import LLMError
from vocab_bot.llm.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from vocab_bot.llm.schema import ChunkResponse

if TYPE_CHECKING:
    from vocab_bot.core.models import RawItem, Sense
    from vocab_bot.llm.keypool import GeminiKeyPool

_HTTP_TOO_MANY_REQUESTS = 429
_MAX_ATTEMPTS = 4


class _RateLimited(Exception):
    """Internal signal that a 429 occurred for the given key."""

    def __init__(self, key: str) -> None:
        super().__init__("rate limited")
        self.key = key


class GeminiLanguageModel:
    """Concrete ``LanguageModel`` backed by google-genai + a key pool."""

    def __init__(self, key_pool: GeminiKeyPool, *, model: str) -> None:
        self._pool = key_pool
        self._model = model

    async def enrich(self, items: list[RawItem], *, sense_hint: str | None = None) -> list[Sense]:
        """Enrich a chunk of items into :class:`Sense` objects (order preserved)."""
        if not items:
            return []
        prompt = build_user_prompt(items)
        response = await self._generate_with_retry(prompt)
        return [out.to_sense() for out in response.items]

    async def _generate_with_retry(self, prompt: str) -> ChunkResponse:
        retrying = AsyncRetrying(
            retry=retry_if_exception_type(_RateLimited),
            stop=stop_after_attempt(_MAX_ATTEMPTS),
            wait=wait_exponential(multiplier=0.5, max=8),
            reraise=False,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._generate_once(prompt)
        except Exception as exc:  # tenacity RetryError or final _RateLimited
            raise LLMError("Gemini enrichment failed") from exc
        raise LLMError("Gemini enrichment failed")  # pragma: no cover (unreachable)

    async def _generate_once(self, prompt: str) -> ChunkResponse:
        key = await self._pool.acquire()
        client = genai.Client(api_key=key)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ChunkResponse,
            temperature=0.4,
        )
        try:
            result = await client.aio.models.generate_content(
                model=self._model, contents=prompt, config=config
            )
        except genai_errors.APIError as exc:
            if getattr(exc, "code", None) == _HTTP_TOO_MANY_REQUESTS:
                self._pool.penalize(key)
                raise _RateLimited(key) from exc
            raise LLMError(f"Gemini API error: {exc}") from exc

        return self._parse(result)

    @staticmethod
    def _parse(result: types.GenerateContentResponse) -> ChunkResponse:
        parsed = getattr(result, "parsed", None)
        if isinstance(parsed, ChunkResponse):
            return parsed
        text = result.text
        if not text:
            raise LLMError("Gemini returned an empty response")
        try:
            return ChunkResponse.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError("Gemini returned malformed JSON") from exc
