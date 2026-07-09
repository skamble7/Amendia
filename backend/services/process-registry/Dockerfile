# backend/services/process-registry/Dockerfile
# Build context is the repo root. The repo layout is preserved under /src so the
# service's `amendia-* = { path = "../../../libs..." }` sources resolve the same way
# in the image as they do locally.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

# 1) Shared libraries (amendia_common, then amendia_contracts which depends on it).
COPY libs /src/libs
RUN uv pip install --system /src/libs \
 && uv pip install --system /src/libs/amendia_contracts \
 && uv pip install --system /src/libs/amendia_auth

# 2) Service dependencies + package.
COPY backend/services/process-registry/pyproject.toml /src/backend/services/process-registry/pyproject.toml
COPY backend/services/process-registry/app /src/backend/services/process-registry/app
RUN uv pip install --system /src/backend/services/process-registry

# 3) The seed dataset the registry onboards through its own APIs (lives in agent-runtime).
COPY backend/services/agent-runtime/seed /src/backend/services/agent-runtime/seed
ENV REGISTRY_SEED_DIR=/src/backend/services/agent-runtime/seed/wire-repair-standard

WORKDIR /src/backend/services/process-registry

# 4) Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser /src
USER appuser

EXPOSE 8084
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8084"]
