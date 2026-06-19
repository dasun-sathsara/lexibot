"""MAI-Voice-2 synthesizer over the Azure Speech SDK.

The Azure SDK is synchronous, so each synthesis runs in a worker thread via
``asyncio.to_thread`` to keep the event loop free. Input is SSML (built by
:mod:`vocab_bot.tts.ssml`) at 24 kHz mp3. A cancelled synthesis surfaces as ``TTSError``;
the worker decides whether to retry (transient) or skip (non-retryable 400, RETRY-06).
"""

from __future__ import annotations

import asyncio

import azure.cognitiveservices.speech as speechsdk

from vocab_bot.core.exceptions import TTSError
from vocab_bot.tts.ssml import build_ssml

_OUTPUT_FORMAT = speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3


class MaiVoiceSynthesizer:
    """Concrete ``Synthesizer`` for MAI-Voice-2 on Azure AI Foundry."""

    def __init__(self, *, speech_key: str, endpoint: str, gender: str = "female") -> None:
        self._gender = gender
        self._config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=endpoint)
        self._config.set_speech_synthesis_output_format(_OUTPUT_FORMAT)

    async def synthesize(self, text: str, *, slow: bool = False) -> bytes:
        ssml = build_ssml(text, gender=self._gender, slow=slow)
        return await asyncio.to_thread(self._synthesize_blocking, ssml)

    def _synthesize_blocking(self, ssml: str) -> bytes:
        # No audio output device: we read the bytes from the result instead.
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=self._config, audio_config=None)
        result = synthesizer.speak_ssml_async(ssml).get()
        reason = result.reason
        if reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return bytes(result.audio_data)
        if reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            raise TTSError(
                f"MAI-Voice synthesis canceled: {details.reason} {details.error_details}"
            )
        raise TTSError(f"MAI-Voice synthesis failed: {reason}")
