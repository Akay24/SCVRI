# syntax=docker/dockerfile:1.7
# =============================================================
# Supplier Management Service — multi-stage production image
# =============================================================

# ---- Stage 1: builder ----------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast wheel builds
RUN pip install --no-cache-dir uv==0.5.14

# Copy shared library first (cache layer)
COPY shared/ /build/shared/

# Copy service source
COPY services/supplier-management/ /build/service/

# Install all dependencies into /install prefix
RUN uv pip install --system --no-cache \
    --find-links /build/shared/dist \
    /build/shared \
    /build/service

# ---- Stage 2: runtime ----------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

# Non-root user
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --shell /bin/bash --create-home appuser

# Runtime libs only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY --chown=appuser:appgroup services/supplier-management/src /app/src

USER appuser

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8001

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "supplier_management.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--workers", "2", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--access-log", \
     "--log-config", "/app/src/supplier_management/log_config.json"]
