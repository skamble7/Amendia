# platform/config-forge-service/Dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

COPY platform/config-forge-service/pyproject.toml /app/pyproject.toml
COPY platform/config-forge-service/app /app/app
RUN uv pip install --system /app

EXPOSE 8040
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8040"]
