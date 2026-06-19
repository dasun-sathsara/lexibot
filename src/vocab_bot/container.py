"""Composition root.

Builds the concrete adapters and injects them. Nothing else in the codebase constructs an
SDK client directly; swapping an adapter is a change here only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from vocab_bot.anki.connect import AnkiConnect
from vocab_bot.anki.upsert import AnkiUpsertGateway
from vocab_bot.config import Settings
from vocab_bot.core.pipeline import Pipeline, PipelineLimits
from vocab_bot.llm.gemini import GeminiLanguageModel
from vocab_bot.llm.keypool import GeminiKeyPool
from vocab_bot.tts.mai_voice import MaiVoiceSynthesizer


@dataclass(slots=True)
class WorkerContext:
    """Adapter graph used by the ARQ worker."""

    http: httpx.AsyncClient
    pipeline: Pipeline
    llm: GeminiLanguageModel
    anki: AnkiUpsertGateway


def build_pipeline(settings: Settings, http: httpx.AsyncClient) -> WorkerContext:
    """Construct the full adapter graph from settings."""
    key_pool = GeminiKeyPool(settings.gemini_keys_plain, cooldown_s=settings.gemini_cooldown_s)
    llm = GeminiLanguageModel(key_pool, model=settings.gemini_model)
    tts = MaiVoiceSynthesizer(
        speech_key=settings.azure_speech_key.get_secret_value(),
        endpoint=settings.azure_speech_endpoint,
        gender=settings.voice_gender,
    )
    connect = AnkiConnect(settings.ankiconnect_url, http)
    anki = AnkiUpsertGateway(
        connect,
        deck=settings.target_deck,
        note_type=settings.note_type,
        tz=settings.tz,
    )
    pipeline = Pipeline(
        tts,
        anki,
        gender=settings.voice_gender,
        limits=PipelineLimits.from_key_count(len(settings.gemini_api_keys)),
    )
    return WorkerContext(http=http, pipeline=pipeline, llm=llm, anki=anki)


async def build_worker_context(settings: Settings) -> dict[str, Any]:
    """Build the ARQ worker context dict."""
    http = httpx.AsyncClient(timeout=30.0)
    ctx = build_pipeline(settings, http)
    return {"pipeline": ctx.pipeline, "llm": ctx.llm, "anki": ctx.anki, "http": http}


async def close_worker_context(ctx: dict[str, Any]) -> None:
    http = ctx.get("http")
    if isinstance(http, httpx.AsyncClient):
        await http.aclose()


async def create_redis_pool(settings: Settings) -> ArqRedis:
    """Create the ARQ Redis pool used by the bot to enqueue jobs."""
    return await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
