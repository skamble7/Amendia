# Mock Pega orchestrator (FastAPI, port 9095) — ADR-063 cohort worked example scaffolding.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=9095 \
    PEGA_STUB_HOST=0.0.0.0

WORKDIR /app

# Install the package (deps from pyproject) — metadata first for layer caching.
COPY pyproject.toml README.md* ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 9095

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9095/health', timeout=2).status==200 else 1)"

CMD ["pega-stub"]
