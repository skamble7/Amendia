# Deterministic wire-transfer-exception MCP server (streamable HTTP, port 8060).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8060 \
    MCP_HOST=0.0.0.0

WORKDIR /app

# Install the package (deps resolved from pyproject) — copy metadata first for layer caching.
COPY pyproject.toml README.md* ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8060

# No curl in slim; use a stdlib health probe against /health.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8060/health', timeout=2).status==200 else 1)"

CMD ["wire-transfer-exception-mcp"]
