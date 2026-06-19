# syntax=docker/dockerfile:1.7
# Multi-stage, uv-based build (architecture §12).

# ---- builder: resolve + install deps into a venv -----------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached layer), without the project itself.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now install the project.
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime: slim, non-root -------------------------------------------------
FROM python:3.12-slim AS runtime

# Create an unprivileged user and a writable data dir for the SQLite db.
RUN groupadd --system app && useradd --system --gid app --create-home app \
    && mkdir -p /app/data && chown -R app:app /app

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src

USER app

EXPOSE 8080

# Default: the webhook app. The worker overrides this in docker-compose.
CMD ["python", "-m", "vocab_bot"]
