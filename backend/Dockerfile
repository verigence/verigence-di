FROM python:3.12-slim AS base

WORKDIR /app

# System deps for opencv-headless + python-magic + asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

COPY pyproject.toml .

# ── Development target (includes dev deps) ────────────────────────────────────
FROM base AS development
COPY src/ ./src/
RUN uv pip install --system -e ".[dev]"
CMD ["uvicorn", "verigence.di.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Production build target ────────────────────────────────────────────────────
FROM base AS production
COPY src/ ./src/
RUN uv pip install --system .
COPY alembic/ ./alembic/
COPY alembic.ini .
# Migration 0020 verifies and reads the frozen Wave-1 semantic mapping at
# /docs/schema-v2 inside the deployed image. Keep this byte-identical to the
# reviewed root docs copy; CI has a drift check.
COPY schema-v2-assets/ /docs/schema-v2/

# Default to API; Railway overrides the start command for the factory app.
CMD ["uvicorn", "verigence.di.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
