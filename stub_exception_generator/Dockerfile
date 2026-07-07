# stub_exception_generator/Dockerfile
# Build context is the repo root (so both `libs/` and `stub_exception_generator/` are visible).
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

# 1) Shared library (installs `amendia_common` so the service dep is satisfied).
COPY libs /libs
RUN uv pip install --system /libs

# 2) Service dependencies + package.
COPY stub_exception_generator/pyproject.toml /app/pyproject.toml
COPY stub_exception_generator/app /app/app
RUN uv pip install --system /app

# 3) Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser /app
USER appuser

EXPOSE 8081
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
