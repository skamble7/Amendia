# app/routers/generators.py
"""Discovery endpoint — a domain-neutral catalog of trigger *generators* the UI can drive without knowing any
domain. Each generator advertises the stub POST endpoint that raises it and a set of scenarios
(``id`` / ``label`` / ``body``). The scenarios are DERIVED from the canonical sources — the wire
``ReasonCode`` set and the dine-in ``GenerateTicketRequest`` demo flags — so the catalog can never drift from
what those generators actually accept."""
from __future__ import annotations

from typing import Any, Dict, List, get_args

from fastapi import APIRouter

from app.generator import NARRATIVES
from app.models.api import ReasonCode
from app.models.dining_api import GenerateTicketRequest

router = APIRouter(tags=["generators"])


def _wire_scenarios() -> List[Dict[str, Any]]:
    """One scenario per reason code the triage rule matches — id/body from ``ReasonCode``, a short label from
    the canonical narrative (no new literals)."""
    out: List[Dict[str, Any]] = []
    for code in get_args(ReasonCode):
        short = NARRATIVES.get(code, "").split(";")[0].split(".")[0].strip() or code
        out.append({"id": code, "label": f"{code} · {short}", "body": {"reason_code": code}})
    return out


# UI copy for each dine-in demo flag. Keys are validated against the model's boolean flags below, so a rename
# or removal surfaces at import rather than as a dead UI option.
_DINEIN_FLAG_LABELS = {
    "include_86_item": "86'd item · order-revise loop",
    "allergen_conflict": "Allergen conflict · allergen-revise loop",
    "tender_declined": "Declined tender · payment-resolve loop",
}


def _dinein_scenarios() -> List[Dict[str, Any]]:
    """The clean 'happy path' (empty body) plus one scenario per boolean demo flag on
    ``GenerateTicketRequest`` — body ``{flag: True}``, derived from the model itself."""
    flags = [name for name, f in GenerateTicketRequest.model_fields.items()
             if f.annotation is bool and f.default is False]
    unknown = set(_DINEIN_FLAG_LABELS) - set(flags)
    if unknown:  # guard against drift between this catalog and the request model
        raise RuntimeError(f"generators catalog references unknown dine-in flags: {sorted(unknown)}")
    out: List[Dict[str, Any]] = [{"id": "happy", "label": "Happy path", "body": {}}]
    for flag in flags:
        label = _DINEIN_FLAG_LABELS.get(flag)
        if label is not None:
            out.append({"id": flag, "label": label, "body": {flag: True}})
    return out


def build_catalog() -> Dict[str, Any]:
    """The generator catalog (computed from the canonical model sources)."""
    return {
        "generators": [
            {"id": "wire", "label": "Wire exception", "endpoint": "/exceptions/generate",
             "scenarios": _wire_scenarios()},
            {"id": "dine_in", "label": "Restaurant dine-in", "endpoint": "/tickets/generate",
             "scenarios": _dinein_scenarios()},
        ]
    }


@router.get("/generators")
async def list_generators() -> Dict[str, Any]:
    """List the trigger generators the UI can offer — each with its stub endpoint + demo scenarios."""
    return build_catalog()
