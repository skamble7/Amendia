# backend/services/platform/identity/Dockerfile
# Build context is the repo root so both `libs/` and the service are visible.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

# 1) Shared libraries: amendia_common, amendia_contracts (deps on common), amendia_auth.
COPY libs /src/libs
RUN uv pip install --system /src/libs \
 && uv pip install --system /src/libs/amendia_contracts \
 && uv pip install --system /src/libs/amendia_auth

# 2) Service dependencies + package.
COPY backend/services/platform/identity/pyproject.toml /src/backend/services/platform/identity/pyproject.toml
COPY backend/services/platform/identity/app /src/backend/services/platform/identity/app
RUN uv pip install --system /src/backend/services/platform/identity

WORKDIR /src/backend/services/platform/identity

# 3) Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser /src
USER appuser

EXPOSE 8086
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086"]
