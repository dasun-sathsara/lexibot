"""structlog configuration with secret scrubbing.

A processor walks the event dict and renders any :class:`~pydantic.SecretStr` value as a
fixed mask so credentials never reach the logs (SEC-01/02).
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog
from pydantic import SecretStr

MASK = "**********"


def scrub_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace any ``SecretStr`` value anywhere in the event dict with a mask."""
    return {k: _scrub_value(v) for k, v in event_dict.items()}


def _scrub_value(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return MASK
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_scrub_value(v) for v in value)
    return value


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit JSON to stdout with secret scrubbing."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), 20))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            scrub_secrets,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), 20)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
