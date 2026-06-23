"""Composition root.

Builds the concrete adapters and injects them. Nothing else in the codebase constructs an
SDK client directly; swapping an adapter is a change here only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from aiogram import Bot
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from lexibot.anki.connect import AnkiConnect
from lexibot.anki.upsert import AnkiUpsertGateway
from lexibot.config import Settings
from lexibot.core.pipeline import Pipeline, PipelineLimits
from lexibot.db.engine import create_engine
from lexibot.llm.gemini import GeminiLanguageModel
from lexibot.llm.keypool import GeminiKeyPool
from lexibot.observability.alerts import AdminAlerter
from lexibot.tts.mai_voice import MaiVoiceSynthesizer


@dataclass(slots=True)
class WorkerContext:
    """Adapter graph used by the ARQ worker."""

    http: httpx.AsyncClient
    pipeline: Pipeline
    llm: GeminiLanguageModel
    anki: AnkiUpsertGateway
    engine: Any  # sqlalchemy AsyncEngine
    alerter: AdminAlerter


def build_pipeline(settings: Settings, http: httpx.AsyncClient) -> WorkerContext:
    """Construct the full adapter graph from settings."""
    key_pool = GeminiKeyPool(settings.gemini_keys_plain, cooldown_s=settings.gemini_cooldown_s)
    llm = GeminiLanguageModel(
        key_pool,
        model=settings.gemini_model,
        max_attempts=settings.gemini_max_attempts,
    )
    tts = MaiVoiceSynthesizer(
        speech_key=settings.azure_speech_key.get_secret_value(),
        endpoint=settings.azure_speech_endpoint,
        gender=settings.voice_gender,
    )
    connect = AnkiConnect(
        settings.ankiconnect_url,
        http,
        max_attempts=settings.ankiconnect_max_attempts,
    )
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
        limits=PipelineLimits.from_settings(settings),
    )
    engine = create_engine(settings.database_url)
    bot = Bot(token=settings.telegram_token.get_secret_value())
    alerter = AdminAlerter(bot, settings.admin_id)
    return WorkerContext(
        http=http, pipeline=pipeline, llm=llm, anki=anki, engine=engine, alerter=alerter
    )


async def build_worker_context(settings: Settings) -> dict[str, Any]:
    """Build the ARQ worker context dict."""
    http = httpx.AsyncClient(timeout=30.0)
    ctx = build_pipeline(settings, http)
    return {
        "pipeline": ctx.pipeline,
        "llm": ctx.llm,
        "anki": ctx.anki,
        "http": http,
        "engine": ctx.engine,
        "alerter": ctx.alerter,
        "settings": settings,
    }


async def close_worker_context(ctx: dict[str, Any]) -> None:
    http = ctx.get("http")
    if isinstance(http, httpx.AsyncClient):
        await http.aclose()
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    alerter = ctx.get("alerter")
    if isinstance(alerter, AdminAlerter):
        await alerter._bot.session.close()


async def create_redis_pool(settings: Settings) -> ArqRedis:
    """Create the ARQ Redis pool used by the bot to enqueue jobs."""
    return await create_pool(RedisSettings.from_dsn(settings.redis_dsn))
