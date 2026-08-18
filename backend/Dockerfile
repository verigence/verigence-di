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

# ── Development target (includes dev deps, src mounted as volume) ──────────────
FROM base AS development
RUN uv pip install --system -e ".[dev]"
COPY src/ ./src/
CMD ["uvicorn", "verigence.di.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Production build target ────────────────────────────────────────────────────
FROM base AS production
RUN uv pip install --system .
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Default to API; override CMD in Railway for worker / scheduler
CMD ["uvicorn", "verigence.di.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
