# backend/services/agent-runtime/Dockerfile
# Build context is the repo root. The repo layout is preserved under /src so the
# service's `amendia-common = { path = "../../../libs" }` source resolves the same
# way in the image as it does locally.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

# 1) Shared libraries (install amendia_common, then amendia_contracts which depends on it).
#    polyllm[langchain,remote] is pre-installed here (with its provider backends) so the
#    service install below finds it satisfied — it is a path dep, not on a package index.
COPY libs /src/libs
RUN uv pip install --system /src/libs \
 && uv pip install --system /src/libs/amendia_contracts \
 && uv pip install --system /src/libs/amendia_auth \
 && uv pip install --system "/src/libs/polyllm[langchain,remote]"

# 2) Service dependencies + package.
COPY backend/services/agent-runtime/pyproject.toml /src/backend/services/agent-runtime/pyproject.toml
COPY backend/services/agent-runtime/app /src/backend/services/agent-runtime/app
COPY backend/services/agent-runtime/seed /src/backend/services/agent-runtime/seed
# The capability-worker (ADR-020) — a sibling package launched via `python -m worker.main`
# from WORKDIR (below). Shipped in the same image; not pip-installed (imported from cwd).
COPY backend/services/agent-runtime/worker /src/backend/services/agent-runtime/worker
RUN uv pip install --system /src/backend/services/agent-runtime

WORKDIR /src/backend/services/agent-runtime

# The app package is installed into site-packages, so point the seed loader at the
# copied seed tree explicitly (the __file__-relative default would resolve into
# site-packages).
ENV AGENTRT_SEED_DIR=/src/backend/services/agent-runtime/seed/wire-repair-standard

# 3) Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser /src
USER appuser

EXPOSE 8083
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8083"]
