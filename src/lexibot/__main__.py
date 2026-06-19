"""`python -m lexibot` -> launch the webhook app with uvicorn."""

from __future__ import annotations

import uvicorn

from lexibot.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "lexibot.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8080,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
