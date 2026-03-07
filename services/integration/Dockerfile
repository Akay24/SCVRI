# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir hatchling

COPY shared/ /shared/
COPY services/integration/ /build/

RUN pip install --no-cache-dir --prefix=/install \
    -e "file:///shared" \
    -e ".[dev]" \
    . 2>/dev/null || \
    pip install --no-cache-dir --prefix=/install .

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY services/integration/src/ /app/src/

ENV PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8005

CMD ["uvicorn", "integration.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8005", \
     "--workers", "2", \
     "--loop", "uvloop"]
