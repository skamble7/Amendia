# amendia_contracts/artifact_schema.py
"""Contract 3 — Artifact schema registration envelope.

The embedded ``json_schema`` is a free-form object here; its well-formedness as a
draft 2020-12 schema is meta-validated by the seed loader (jsonschema), not by
Pydantic. Cross-version compatibility diffing is # registry-validation (later).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from amendia_contracts.common import ArtifactKey, ContractModel, SemVerStr, TimestampsMixin


class Compatibility(str, Enum):
    BACKWARD = "backward"
    NONE = "none"


class ArtifactStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ArtifactSchemaRegistration(ContractModel, TimestampsMixin):
    artifact_key: ArtifactKey
    version: SemVerStr
    title: str
    description: Optional[str] = None
    json_schema: Dict[str, Any]
    compatibility: Compatibility = Compatibility.BACKWARD
    tags: Optional[List[str]] = None
    status: ArtifactStatus
