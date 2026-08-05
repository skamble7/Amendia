# backend/services/platform/config-forge-service/Dockerfile
# Build context is the repo root (mirrors the other platform services), so paths
# below are repo-root-relative. ConfigForge's only amendia_* lib is amendia_telemetry (ADR-058).
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

# Shared telemetry lib (path dep, not on an index) — pre-install so the service install finds it satisfied.
COPY libs /src/libs
RUN uv pip install --system /src/libs/amendia_telemetry

# Service dependencies + package. `scripts/` is included so the seed can run in-container.
COPY backend/services/platform/config-forge-service/pyproject.toml /src/backend/services/platform/config-forge-service/pyproject.toml
COPY backend/services/platform/config-forge-service/app /src/backend/services/platform/config-forge-service/app
COPY backend/services/platform/config-forge-service/scripts /src/backend/services/platform/config-forge-service/scripts
RUN uv pip install --system /src/backend/services/platform/config-forge-service

WORKDIR /src/backend/services/platform/config-forge-service

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser /src
USER appuser

EXPOSE 8040
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8040"]
