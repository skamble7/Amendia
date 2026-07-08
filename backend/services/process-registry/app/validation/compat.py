# app/validation/compat.py
"""Backward-compatibility diff between two artifact JSON Schemas.

Compares a NEW schema against the PREVIOUS registered version and classifies each
structural change. Conservative: any change we can't confidently call non-breaking
is reported as breaking. Findings carry JSON-pointer paths.

BREAKING: removed property; property added to `required`; type narrowed/changed;
enum values removed; `additionalProperties` tightened (true→false).
NON-BREAKING: new optional property; enum values added; `additionalProperties`
loosened (false→true); description/title/examples changes.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from pydantic import BaseModel


class CompatFinding(BaseModel):
    breaking: bool
    code: str
    path: str
    message: str


def _is_obj(s: Any) -> bool:
    return isinstance(s, Mapping)


def _type_set(schema: Mapping[str, Any]) -> Optional[set]:
    t = schema.get("type")
    if t is None:
        return None
    return set(t) if isinstance(t, list) else {t}


def diff_schemas(old: Mapping[str, Any], new: Mapping[str, Any]) -> List[CompatFinding]:
    """Return all compat findings; empty ⇒ fully backward-compatible."""
    findings: List[CompatFinding] = []
    _diff(old, new, "", findings)
    return findings


def has_breaking(findings: List[CompatFinding]) -> bool:
    return any(f.breaking for f in findings)


def _diff(old: Mapping[str, Any], new: Mapping[str, Any], path: str, out: List[CompatFinding]) -> None:
    if not _is_obj(old) or not _is_obj(new):
        return

    # --- type change / narrowing ---
    ot, nt = _type_set(old), _type_set(new)
    if ot is not None and nt is not None and ot != nt:
        if nt <= ot:  # narrowed (subset) — breaking
            out.append(CompatFinding(breaking=True, code="type_narrowed", path=path or "/",
                                     message=f"type narrowed {sorted(ot)} → {sorted(nt)}"))
        else:
            out.append(CompatFinding(breaking=True, code="type_changed", path=path or "/",
                                     message=f"type changed {sorted(ot)} → {sorted(nt)}"))

    # --- enum values removed (breaking) / added (non-breaking) ---
    if "enum" in old or "enum" in new:
        oe = set(map(_hashable, old.get("enum", []) or []))
        ne = set(map(_hashable, new.get("enum", []) or []))
        removed = oe - ne
        added = ne - oe
        if removed:
            out.append(CompatFinding(breaking=True, code="enum_values_removed", path=path or "/",
                                     message=f"enum values removed: {sorted(map(str, removed))}"))
        if added:
            out.append(CompatFinding(breaking=False, code="enum_values_added", path=path or "/",
                                     message=f"enum values added: {sorted(map(str, added))}"))

    # --- additionalProperties tighten/loosen ---
    oap, nap = old.get("additionalProperties"), new.get("additionalProperties")
    if oap != nap and (oap is not None or nap is not None):
        # Treat only the boolean true→false as breaking; false→true as non-breaking.
        if oap is not False and nap is False:
            out.append(CompatFinding(breaking=True, code="additional_properties_tightened", path=path or "/",
                                     message="additionalProperties tightened to false"))
        elif oap is False and nap is not False:
            out.append(CompatFinding(breaking=False, code="additional_properties_loosened", path=path or "/",
                                     message="additionalProperties loosened from false"))

    # --- required additions (breaking) ---
    old_req = set(old.get("required", []) or [])
    new_req = set(new.get("required", []) or [])
    for name in sorted(new_req - old_req):
        out.append(CompatFinding(breaking=True, code="required_added", path=f"{path}/required",
                                 message=f"property '{name}' added to required"))

    # --- properties: removed (breaking), added optional (non-breaking), recurse into shared ---
    old_props = old.get("properties", {}) if _is_obj(old.get("properties", {})) else {}
    new_props = new.get("properties", {}) if _is_obj(new.get("properties", {})) else {}
    for name in sorted(set(old_props) - set(new_props)):
        out.append(CompatFinding(breaking=True, code="property_removed", path=f"{path}/properties/{name}",
                                 message=f"property '{name}' removed"))
    for name in sorted(set(new_props) - set(old_props)):
        breaking = name in new_req
        out.append(CompatFinding(breaking=breaking,
                                 code="required_property_added" if breaking else "optional_property_added",
                                 path=f"{path}/properties/{name}",
                                 message=f"property '{name}' added"
                                         + (" as required" if breaking else " (optional)")))
    for name in sorted(set(old_props) & set(new_props)):
        _diff(old_props[name], new_props[name], f"{path}/properties/{name}", out)

    # --- array items: recurse ---
    if _is_obj(old.get("items")) and _is_obj(new.get("items")):
        _diff(old["items"], new["items"], f"{path}/items", out)


def _hashable(v: Any) -> Any:
    try:
        hash(v)
        return v
    except TypeError:
        return str(v)
