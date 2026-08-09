# src/pega_stub/main.py
"""Console entrypoint: run the mock Pega orchestrator with uvicorn."""
from __future__ import annotations

import uvicorn

from .config import settings


def main() -> None:
    uvicorn.run("pega_stub.app:app", host=settings.host, port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
