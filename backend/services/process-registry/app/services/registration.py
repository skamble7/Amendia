# app/services/registration.py
"""Artifact-schema registration pipeline (shared by the router and the seeder).

Steps: (2) draft-2020-12 meta-validation, (3) conventions ($id derivation, root object,
additionalProperties warning), (4) $ref whitelist to registered $ids, (5) backward-compat
diff on minor/patch bumps. Step (1) — envelope model validation — happens when the caller
constructs the ``ArtifactSchemaRegistration``.
"""
from __future__ import annotations

import logging
import re
from typing import Any, List, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from packaging.version import Version

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.base import DuplicateError
from app.validation.compat import diff_schemas, has_breaking

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^https://amendia\.dev/schemas/artifacts/([a-z0-9_]+)/([a-z0-9_]+)/(\d+\.\d+\.\d+)\.json$")


class RegistrationError(Exception):
    def __init__(self, errors: List[str], warnings: List[str] | None = None) -> None:
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("; ".join(errors))


def _expected_id(artifact_key: str, version: str) -> str:
    _, domain, name = artifact_key.split(".", 2)
    return f"https://amendia.dev/schemas/artifacts/{domain}/{name}/{version}.json"


def _collect_refs(node: Any, out: List[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                out.append(v)
            else:
                _collect_refs(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, out)


async def validate_schema(reg: ArtifactSchemaRegistration, repo: ArtifactSchemaRepository) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    js = reg.json_schema

    try:
        Draft202012Validator.check_schema(js)
    except SchemaError as exc:
        errors.append(f"json_schema is not a valid draft 2020-12 schema: {exc.message}")

    if js.get("type") != "object":
        errors.append("json_schema root 'type' must be 'object'")
    # ADR-052 E2: the canonical $id is DERIVED and OVERRIDDEN at registration (see register_schema) — no author
    # hand-matches it to the domain — so it is NOT validated here.
    if js.get("additionalProperties") is not False:
        warnings.append("json_schema should set additionalProperties=false")

    refs: List[str] = []
    _collect_refs(js, refs)
    for ref in refs:
        m = _ID_RE.match(ref)
        if not m:
            errors.append(f"$ref '{ref}' is not an amendia.dev registered-schema $id")
            continue
        domain, name, ver = m.groups()
        # ADR-060: a $ref must resolve within the SAME pack's owned schemas (a pack is self-contained).
        if await repo.get(reg.pack_key, reg.pack_version, f"art.{domain}.{name}", ver) is None:
            errors.append(f"$ref '{ref}' points at an unregistered schema")

    if reg.compatibility.value == "backward":
        prev = await repo.previous_version(reg.pack_key, reg.pack_version, reg.artifact_key, reg.version)
        if prev is not None and Version(reg.version).major == Version(prev.version).major:
            for f in diff_schemas(prev.json_schema, js):
                if f.breaking:
                    errors.append(f"breaking change at {f.path}: {f.message}")

    return errors, warnings


async def register_schema(reg: ArtifactSchemaRegistration, repo: ArtifactSchemaRepository) -> ArtifactSchemaRegistration:
    """Full pipeline; raises RegistrationError on hard failures, DuplicateError on 409."""
    # ADR-052 E2: DERIVE the canonical $id from the artifact key + version and OVERRIDE whatever was supplied
    # (a foreign-domain $id, or none) — the author never hand-matches it. Applies to introspected, authored, and
    # trigger artifacts alike (all register through here). A supplied $id is normalized, not validated/rejected.
    if isinstance(reg.json_schema, dict):
        reg.json_schema["$id"] = _expected_id(reg.artifact_key, reg.version)
    errors, warnings = await validate_schema(reg, repo)
    if errors:
        raise RegistrationError(errors, warnings)
    if warnings:
        logger.warning("artifact schema %s@%s registered with warnings: %s",
                       reg.artifact_key, reg.version, warnings)
    return await repo.insert(reg)
