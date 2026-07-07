# platform/notification-service/Dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Install shared libs (editable) — copy project root + package dir
COPY libs/pyproject.toml /tmp/libs/pyproject.toml
COPY libs /tmp/libs/libs
RUN pip install --no-cache-dir -e /tmp/libs

# (optional) sanity check
RUN python - <<'PY'
import importlib
m = importlib.import_module("libs.raina_common.events")
print("OK:", m.__file__)
PY

# -------------------------------
# 2) Install notification service deps
# -------------------------------
COPY platform/notification-service/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .

# -------------------------------
# 3) Copy the service code
# -------------------------------
COPY platform/notification-service/app /app/app

EXPOSE 8016
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8016"]
