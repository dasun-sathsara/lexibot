"""CONF-01/02/03 and SEC-01/02 — config parsing + secret hygiene (test-spec §12)."""

from __future__ import annotations

import json

import pytest
import structlog
from pydantic import SecretStr, ValidationError

from vocab_bot.config import Settings
from vocab_bot.logging import MASK, scrub_secrets

_BASE_ENV = {
    "VB_TELEGRAM_TOKEN": "zztelegramsecretzz",
    "VB_AZURE_SPEECH_KEY": "zzazuresecretzz",
    "VB_AZURE_SPEECH_ENDPOINT": "https://example.cognitiveservices.azure.com/",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Strip any ambient ``VB_*`` vars so tests are hermetic, and ignore .env."""
    import os

    for key in list(os.environ):
        if key.startswith("VB_"):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


def _set(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_conf_01_gemini_keys_parsed_to_list(clean_env: pytest.MonkeyPatch) -> None:
    _set(clean_env, {**_BASE_ENV, "VB_GEMINI_API_KEYS": "k1,k2,k3"})
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert len(s.gemini_api_keys) == 3
    assert s.gemini_keys_plain == ["k1", "k2", "k3"]


def test_conf_02_allowed_ids_parsed_to_ints(clean_env: pytest.MonkeyPatch) -> None:
    _set(clean_env, {**_BASE_ENV, "VB_GEMINI_API_KEYS": "k1", "VB_ALLOWED_IDS": "111,222"})
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.allowed_ids == [111, 222]


def test_conf_03_missing_required_secret_raises(clean_env: pytest.MonkeyPatch) -> None:
    _set(
        clean_env,
        {
            "VB_AZURE_SPEECH_KEY": "azkey",
            "VB_AZURE_SPEECH_ENDPOINT": "https://x/",
            "VB_GEMINI_API_KEYS": "k1",
        },
    )
    # Missing VB_TELEGRAM_TOKEN -> fail fast at startup.
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_sec_01_secretstr_masked_in_logs() -> None:
    out = scrub_secrets(None, "info", {"token": SecretStr("super-secret"), "n": 1})
    assert out["token"] == MASK
    assert out["n"] == 1
    assert "super-secret" not in json.dumps(out)


def test_sec_01_nested_secret_masked() -> None:
    out = scrub_secrets(None, "info", {"cfg": {"keys": [SecretStr("a"), SecretStr("b")]}})
    assert out["cfg"]["keys"] == [MASK, MASK]


def test_sec_02_secret_not_leaked_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    _set(clean_env, {**_BASE_ENV, "VB_GEMINI_API_KEYS": "k1,k2"})
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    # pydantic SecretStr repr/str is masked; full settings repr must not leak the token.
    assert "zztelegramsecretzz" not in repr(s)
    assert s.telegram_token.get_secret_value() == "zztelegramsecretzz"


def test_sec_01_end_to_end_through_structlog(capsys: pytest.CaptureFixture[str]) -> None:
    from vocab_bot.logging import configure_logging

    configure_logging("INFO")
    log = structlog.get_logger("test")
    log.info("login", token=SecretStr("hunter2"))
    captured = capsys.readouterr().out
    assert "hunter2" not in captured
    assert MASK in captured
