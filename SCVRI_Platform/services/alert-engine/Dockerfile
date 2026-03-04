# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

RUN pip install uv

WORKDIR /build
COPY shared/ shared/
COPY services/alert-engine/ services/alert-engine/

WORKDIR /build/services/alert-engine
RUN uv pip install --system --no-cache ".[dev]"

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY services/alert-engine/src /app/src
COPY services/alert-engine/src/alert_engine/templates /app/src/alert_engine/templates

ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED="1"

EXPOSE 8004

CMD ["uvicorn", "alert_engine.main:app", "--host", "0.0.0.0", "--port", "8004", "--workers", "2"]
