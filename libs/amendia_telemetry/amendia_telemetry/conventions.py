# amendia_telemetry/conventions.py
"""Amendia's OpenTelemetry semantic conventions — the single ``amendia.*`` attribute namespace.

**All attributes are structural.** No pack or domain term (nothing about wires, payments,
parties, …) ever enters a span, log, event, resource, or label. This module is the review
gate for domain-neutrality (ADR-058 §4): instrumentation reads data that already exists
(`actor_entry`, `input_map`, `schema_ref`, HITL decision fields) and maps it onto these keys.

Some keys (decision / egress / rationale) are defined here now but only *populated* in later
phases (B/C); they live here so the vocabulary is fixed and referenced from one place.
"""
from __future__ import annotations

# --- resource / instance identity ---
CORRELATION_ID = "amendia.correlation_id"
PROCESS_INSTANCE_ID = "amendia.process_instance_id"
PACK_KEY = "amendia.pack_key"
PACK_VERSION = "amendia.pack_version"

# --- element / actor (execution) ---
ELEMENT_ID = "amendia.element_id"
ACTOR = "amendia.actor"            # capability id or user id
ACTOR_KIND = "amendia.actor_kind"  # capability | human | timer
ROLE = "amendia.role"

# --- lineage (artifacts) ---
ARTIFACT_KEY = "amendia.artifact_key"
SCHEMA_REF = "amendia.schema_ref"

# --- execution substrate ---
EXECUTION_MODE = "amendia.execution_mode"  # native | nemoclaw
SIMULATION = "amendia.simulation"

# --- sandbox correlation (nemoclaw) ---
EXEC_META_TRACE_ID = "amendia.exec_meta.otlp_trace_id"

# --- governance / explainability (defined now, populated in Phases B/C) ---
DECISION = "amendia.decision"
DECIDED_BY = "amendia.decided_by"
SOD_SATISFIED = "amendia.sod_satisfied"
EGRESS_DECISION = "amendia.egress.decision"
EGRESS_HOST = "amendia.egress.host"
RATIONALE = "amendia.rationale"
# ADR-058 Phase C: cap the captured agent rationale so spans / logs / audit rows don't grow unbounded.
RATIONALE_MAX_CHARS = 1200

# Resource attribute keys (deployment-level, set once at bootstrap).
RESOURCE_SERVICE_NAMESPACE = "amendia"
