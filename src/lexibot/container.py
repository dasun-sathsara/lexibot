"""Composition root: builds adapters and the in-process runner.
Prefer constructing SDK clients through this module."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncEngine

from lexibot.anki.connect import AnkiConnect
from lexibot.anki.upsert import AnkiUpsertGateway
from lexibot.config import Settings
from lexibot.core.pipeline import Pipeline, PipelineLimits
from lexibot.core.runner import PipelineRunner
from lexibot.db.engine import create_engine
from lexibot.llm.gemini import GeminiLanguageModel
from lexibot.llm.keypool import GeminiKeyPool
from lexibot.observability.alerts import AdminAlerter
from lexibot.tts.mai_voice import MaiVoiceSynthesizer


@dataclass(slots=True)
class PipelineContext:
    """Adapter graph used by the in-process pipeline runner."""

    http: httpx.AsyncClient
    pipeline: Pipeline
    llm: GeminiLanguageModel
    anki: AnkiUpsertGateway
    engine: AsyncEngine
    alerter: AdminAlerter


def build_pipeline(
    settings: Settings, http: httpx.AsyncClient, engine: AsyncEngine
) -> PipelineContext:
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
    alerter = AdminAlerter(Bot(token=settings.telegram_token.get_secret_value()), settings.admin_id)
    return PipelineContext(
        http=http, pipeline=pipeline, llm=llm, anki=anki, engine=engine, alerter=alerter
    )


def build_runner(
    settings: Settings,
    *,
    http: httpx.AsyncClient | None = None,
    engine: AsyncEngine | None = None,
) -> tuple[PipelineRunner, httpx.AsyncClient, AsyncEngine]:
    """Build the runner plus its owned ``http``/``engine`` for the lifespan to close."""
    http = http or httpx.AsyncClient(timeout=30.0)
    engine = engine or create_engine(settings.database_url)
    ctx = build_pipeline(settings, http, engine)
    runner = PipelineRunner(
        pipeline=ctx.pipeline,
        llm=ctx.llm,
        anki=ctx.anki,
        engine=ctx.engine,
        alerter=ctx.alerter,
        settings=settings,
    )
    return runner, http, engine


async def close_runner_resources(
    *, http: httpx.AsyncClient, engine: AsyncEngine, runner: PipelineRunner
) -> None:
    """Drain the runner and close owned resources on shutdown."""
    await runner.drain()
    await http.aclose()
    await engine.dispose()
    alerter = runner._alerter
    if alerter is not None:
        await alerter._bot.session.close()
