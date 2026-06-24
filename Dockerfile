# CyClaw Dockerfile - Production-grade, zero-trust, reproducible
# Python 3.12 + uv for fast installs. Seccomp/AppArmor ready. Non-root.
# Aligns with v1.7.0 pyproject + constraints for hermetic deps; CI uses requirements.txt for compat.

FROM python:3.12-slim-bookworm AS builder

# Install uv (fast, reproducible)
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /bin/uv

WORKDIR /app

# Dependency files first for layer caching
COPY pyproject.toml constraints.txt requirements.txt ./

# Install with uv (preferred for pyproject.toml + constraints + uv.sources for torch CPU)
# Fallback to pip + requirements.txt (proper reqs format) + constraints for legacy/CI alignment.
# Plain pip cannot read [tool.uv.sources], so the fallback pre-installs the CPU torch wheel
# from the PyTorch index first (mirrors ci.yml / pip-audit.yml) before the constrained install,
# otherwise constraints.txt's `torch==2.6.0+cpu` pin is unresolvable on PyPI.
RUN uv pip install --system --no-cache-dir -r pyproject.toml --constraint constraints.txt 2>/dev/null || \
    ( pip install --no-cache-dir torch==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir -r requirements.txt -c constraints.txt )

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

EXPOSE 8787

# Simple healthcheck (assumes /health in gate.py)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://127.0.0.1:8787/health', timeout=4)" || exit 1

# Loopback-only binding (security invariant: CyClaw never binds to 0.0.0.0).
# Port 8787 matches config.yaml api.port.
CMD ["uvicorn", "gate:app", "--host", "127.0.0.1", "--port", "8787", "--log-level", "info"]
