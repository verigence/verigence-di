FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy backend package files
COPY backend/pyproject.toml ./
COPY backend/src ./src

# Install production dependencies only
RUN pip install --no-cache-dir .

EXPOSE 8000

# START_MODE controls which service role this container runs as:
#   api    (default) — uvicorn HTTP server
#   worker           — background processing worker
CMD ["sh", "-c", "\
  if [ \"${START_MODE:-api}\" = \"worker\" ]; then \
    exec python -m verigence.di.workers; \
  else \
    exec uvicorn verigence.di.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}; \
  fi"]
