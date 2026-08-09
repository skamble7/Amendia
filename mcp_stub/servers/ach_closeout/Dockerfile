# Deterministic ACH-exposure CLOSEOUT-segment MCP server (streamable HTTP, port 8077).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8077 \
    MCP_HOST=0.0.0.0

WORKDIR /app

COPY pyproject.toml README.md* ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8077

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8077/health', timeout=2).status==200 else 1)"

CMD ["ach-closeout-mcp"]
