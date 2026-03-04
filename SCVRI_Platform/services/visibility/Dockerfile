# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

RUN pip install uv

WORKDIR /build
COPY shared/ shared/
COPY services/visibility/ services/visibility/

WORKDIR /build/services/visibility
RUN uv pip install --system --no-cache ".[dev]"

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Required by Shapely / GEOS
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY services/visibility/src /app/src

ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED="1"

EXPOSE 8003

CMD ["uvicorn", "visibility.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "2"]
