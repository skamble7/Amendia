# tests/test_content_reconciliation.py
"""ADR-047 D2 — "green must mean populated" (content, not just outcome).

The golden net asserts terminal outcome + artifact-NAME set, so it missed a whole class of re-home drift: a
consumer declaring the OLD field contract (the orphan `investigation_dossier` — `payment_snapshot`/`gpi_status`)
while the MCP producer emits a DIFFERENT shape (`enrich_investigation_output` — `payment`/`parties`/`history`).
Data flowed, but into fields the tool never emits, so the schema-driven human form rendered EMPTY.

This targets that: the artifact a human task receives must VALIDATE against the schema its form renders (the
binding's declared input) AND carry populated fields from the envelope. It fails on the pre-reconciliation
seed (produced data doesn't satisfy the declared `investigation_dossier` required fields) and passes after.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.config import settings
from app.engine.bundle import PackBundle
from tests._mcp_server_tools import server_tool_map
from tests._wire import make_envelope


def _declared_input_schema(pack_dir: Path, element_id: str, input_name: str):
    """The schema a binding's form renders for one input — resolved against the pack's registered schemas."""
    m = json.loads((pack_dir / "manifest.json").read_text())
    binding = next(b for b in m["bindings"] if b["element_id"] == element_id)
    ref = next(i["schema"] for i in binding["inputs"] if i["name"] == input_name)
    key = ref.split("@", 1)[0]
    bundle = PackBundle.from_seed_dir(str(pack_dir))
    return bundle.schemas[f"{key}@1.0.0"]


def test_obtaininfo_dossier_validates_against_its_form_schema_and_is_populated():
    pack_dir = Path(settings.SEED_DIR)
    env = make_envelope("AC01", creditor_name="Novena Pharma SAS")
    # Produce the dossier exactly as the runtime does — the real enrich MCP tool over the envelope.
    dossier = server_tool_map()["enrich_investigation"](
        {"envelope": env, "exception_id": env["exception_id"]})

    # 1) The dossier MUST satisfy the schema Task_ObtainInfo's form renders (its declared `dossier` input).
    #    Pre-reconciliation this is `investigation_dossier` (requires payment_snapshot/gpi_status the tool
    #    never emits) → validation errors → the empty form. Post-reconciliation it is the tool's real shape.
    schema = _declared_input_schema(pack_dir, "Task_ObtainInfo", "dossier")
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(dossier)]
    assert not errors, f"dossier does not match the Task_ObtainInfo form schema (empty render): {errors}"

    # 2) The human-facing fields are actually populated from the envelope — "green" means populated.
    assert dossier["exception_id"] == env["exception_id"]
    assert dossier["payment"], "payment snapshot empty"
    assert any(p.get("name") for p in dossier.get("parties", [])), "no party names in the dossier"
    creditor = env["payment"]["creditor"]["name"]
    assert any(creditor in json.dumps(p) for p in dossier["parties"]), \
        "the creditor from the envelope is not carried into the dossier the analyst sees"


def test_no_consumer_declares_a_field_no_producer_emits():
    # Structural guard for the whole pack: every shared-name input schema must equal the producing binding's
    # output schema (the drift the golden net can't see). Complements the registry gate with a runtime-side check.
    pack_dir = Path(settings.SEED_DIR)
    m = json.loads((pack_dir / "manifest.json").read_text())
    producers = {}
    for b in m["bindings"]:
        for o in (b.get("outputs") or []):
            producers.setdefault(o["name"], set()).add(o["schema"])
    drift = []
    for b in m["bindings"]:
        for i in (b.get("inputs") or []):
            ps = producers.get(i["name"])
            if ps and i["schema"] not in ps:
                drift.append(f"{b['element_id']}: input '{i['name']}'={i['schema']} vs producer {sorted(ps)}")
    assert not drift, "consumer declares a schema no producer emits (re-home drift):\n" + "\n".join(drift)
