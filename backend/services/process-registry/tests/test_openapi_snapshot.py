"""ADR-027 §5 / Phase 1.4 — the committed OpenAPI snapshot must match the live app.

`webui/openapi/registry.json` is the offline source `gen:api` generates the onboarding types
from. `gen:api:check` gates gen/ ↔ snapshot; this test gates snapshot ↔ app, so a backend
contract change that isn't re-dumped fails CI (the snapshot can't silently go stale).
Regenerate with: `python scripts/dump_openapi.py && (cd webui && npm run gen:api)`.
"""
import json
from pathlib import Path

from app.main import create_app

_SNAPSHOT = Path(__file__).resolve().parents[4] / "webui" / "openapi" / "registry.json"


def test_openapi_snapshot_matches_app():
    fresh = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    committed = _SNAPSHOT.read_text()
    assert fresh == committed, (
        "webui/openapi/registry.json is stale — run `python scripts/dump_openapi.py` and "
        "`(cd webui && npm run gen:api)`, then commit the results."
    )
