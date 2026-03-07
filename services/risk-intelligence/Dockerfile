# ─────────────────────────────────────────────
# Stage 1 — dependency builder
# ─────────────────────────────────────────────
FROM python:3.14-slim AS builder

RUN pip install --no-cache-dir uv==0.5.14

WORKDIR /build

# Install shared library first (local path dependency)
COPY shared/ ./shared/
RUN uv pip install --system --no-cache ./shared/

# Install service dependencies
COPY services/risk-intelligence/pyproject.toml ./service/
COPY services/risk-intelligence/src/ ./service/src/
RUN uv pip install --system --no-cache ./service/

# ─────────────────────────────────────────────
# Stage 2 — lean runtime
# ─────────────────────────────────────────────
FROM python:3.14-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -s /sbin/nologin appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/service/src ./src

RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')"

CMD ["uvicorn", "risk_intelligence.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8002", \
     "--workers", "2", \
     "--loop", "uvloop", \
     "--http", "httptools"]
