"""`python -m vocab_bot` -> launch the webhook app with uvicorn."""

from __future__ import annotations

import uvicorn

from vocab_bot.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "vocab_bot.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8080,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
