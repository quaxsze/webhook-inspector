FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
RUN pip install uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app
COPY migrations ./migrations
COPY alembic.ini ./

# Run as non-root user
RUN groupadd -r appuser && useradd -r -u 1001 -g appuser appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000 8001
CMD ["uvicorn", "webhook_inspector.web.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
