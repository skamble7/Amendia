# src/pega_stub/config.py
"""Env-driven config for the mock Pega orchestrator (test/dev scaffolding, ADR-063).

Domain-neutral wiring only: where the trigger store lives, the listen port, and the optional (flagged) cohort-
definition self-registration. No Amendia internals, no owner credentials baked in.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # The stub-trigger-generator's in-network base — the store the ingestor is configured to fetch-back from.
    trigger_store_url: str = os.environ.get("TRIGGER_STORE_URL", "http://stub-trigger-generator:8081")
    # Optional shared internal token → sent as X-Amendia-Internal so POST /triggers passes when auth is strict.
    trigger_store_internal_token: str = os.environ.get("TRIGGER_STORE_INTERNAL_TOKEN", "")
    source: str = os.environ.get("TRIGGER_SOURCE", "pega")

    host: str = os.environ.get("PEGA_STUB_HOST", "0.0.0.0")
    port: int = int(os.environ.get("PORT", "9095"))
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    # ADR-064 SLA e2e: optional override for the `late_closeout` scenario's closeout delay (seconds). When
    # > 0 it overrides the preset's `closeout_delay_seconds` (retune the breach demo without editing code);
    # 0 (default) → use the preset value. Never affects a scenario that declares no delay.
    closeout_delay_override: int = int(os.environ.get("CLOSEOUT_DELAY_SECONDS", "0") or "0")

    # Optional, flagged: self-register the cohort definition on startup via the registry API. Off by default —
    # registering needs role.process.owner, so provide REGISTRY_BEARER (never hardcode owner creds). When off,
    # the operator registers the definition in the webui (the exact close schema is documented in the report).
    register_cohort_on_start: bool = _bool("REGISTER_COHORT_ON_START", False)
    registry_url: str = os.environ.get("REGISTRY_URL", "http://process-registry:8084")
    registry_bearer: str = os.environ.get("REGISTRY_BEARER", "")
    cohort_def_id: str = os.environ.get("COHORT_DEF_ID", "ach_exposure_cohort")


settings = Settings()
