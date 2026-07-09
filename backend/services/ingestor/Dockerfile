# backend/services/ingestor/Dockerfile
# Build context is the repo root. The repo layout is preserved under /src so the
# service's `amendia-common = { path = "../../../libs" }` source resolves the same
# way in the image as it does locally.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

# 1) Shared libraries (amendia_common + amendia_contracts + amendia_auth).
COPY libs /src/libs
RUN uv pip install --system /src/libs \
 && uv pip install --system /src/libs/amendia_contracts \
 && uv pip install --system /src/libs/amendia_auth

# 2) Service dependencies + package (path source ../../../libs → /src/libs).
COPY backend/services/ingestor/pyproject.toml /src/backend/services/ingestor/pyproject.toml
COPY backend/services/ingestor/app /src/backend/services/ingestor/app
RUN uv pip install --system /src/backend/services/ingestor

WORKDIR /src/backend/services/ingestor

# 3) Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser /src
USER appuser

EXPOSE 8082
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
