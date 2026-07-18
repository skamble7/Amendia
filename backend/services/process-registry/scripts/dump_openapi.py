#!/usr/bin/env python
"""Dump the process-registry OpenAPI document to a committed snapshot — OFFLINE.

``FastAPI.openapi()`` builds the schema purely from route/``response_model`` metadata: no DB,
broker, or network. So this produces exactly what ``GET /openapi.json`` would serve, with the
stack down, and lets ``webui``'s ``gen:api`` generate the onboarding types from a committed file
(ADR-027 §5 / Phase 1.4). Output is ``sort_keys``-stable so the snapshot diffs cleanly.

Usage:
    python scripts/dump_openapi.py            # write webui/openapi/registry.json
    python scripts/dump_openapi.py --stdout    # print to stdout (for a freshness check)

Import needs the service settings to load; the repo defaults (auth disabled in dev) suffice — no
IdP/Mongo required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]  # scripts → process-registry → services → backend → repo
SNAPSHOT = _ROOT / "webui" / "openapi" / "registry.json"


def dump() -> str:
    from app.main import create_app

    doc = create_app().openapi()
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main() -> None:
    text = dump()
    if "--stdout" in sys.argv[1:]:
        sys.stdout.write(text)
        return
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(text)
    print(f"wrote {SNAPSHOT.relative_to(_ROOT)} ({len(text)} bytes)")


if __name__ == "__main__":
    main()
