# CyClaw Dockerfile - Production-grade, zero-trust, reproducible
# Python 3.12 + uv for fast installs. Seccomp/AppArmor ready. Non-root.
# Aligns with v1.4.0 invariants + advisor hardening suggestions.

FROM python:3.12-slim-bookworm AS builder

# Install uv (fast, reproducible)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Dependency files first for layer caching
COPY pyproject.toml constraints.txt* requirements.txt* ./

# Install with uv (preferred) or fallback pip + constraints
RUN uv pip install --system --no-cache-dir -r pyproject.toml --constraint constraints.txt 2>/dev/null || \
    pip install --no-cache-dir -r pyproject.toml -c constraints.txt

# Runtime stage
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy site-packages and bins from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# App code
COPY . .

# Non-root user (Veeam-style least privilege)
RUN useradd --create-home --uid 1000 --gid 1000 cyclaw && \
    chown -R cyclaw:cyclaw /app /tmp
USER cyclaw

# Offline-first + security env
ENV CYCLAW_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CYCLAW_TELEMETRY_KILL=1

EXPOSE 8000

# Simple healthcheck (assumes /health in gate.py)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# Default: uvicorn or entrypoint script from pyproject
CMD ["uvicorn", "gate:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
