# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY shared/ /build/shared/
COPY services/iam/pyproject.toml /build/services/iam/
COPY services/iam/src/ /build/services/iam/src/

RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
        "/build/shared" \
        "/build/services/iam[dev]"

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/iam/src/ /app/src/

# RS256 private key (mounted as secret in production)
# Provide via env: IAM_PRIVATE_KEY_PATH or IAM_PRIVATE_KEY (PEM string)
ENV PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "iam.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--loop", "uvloop", \
     "--http", "httptools"]
