# src/pega_stub/registry_client.py
"""Optional, flagged helper: idempotently register the ACH cohort DEFINITION via the registry API.

Off by default (REGISTER_COHORT_ON_START). Registering needs role.process.owner, so a bearer must be supplied
via REGISTRY_BEARER — no owner credentials are ever hardcoded. When the flag is off, the operator registers the
definition in the webui using the close schema documented in the report / `scenarios.COHORT_CLOSE_SCHEMA`.
"""
from __future__ import annotations

import logging

import httpx

from . import scenarios as S
from .config import settings

logger = logging.getLogger(__name__)


async def maybe_register_cohort_definition() -> None:
    """Fail-soft: a missing bearer or a registry hiccup logs and returns — it never blocks startup."""
    if not settings.register_cohort_on_start:
        return
    if not settings.registry_bearer:
        logger.warning("REGISTER_COHORT_ON_START set but REGISTRY_BEARER missing — skipping (register in webui).")
        return
    body = {
        "cohort_def_id": settings.cohort_def_id,
        "display_name": "ACH exposure — cross-system case",
        "description": "Groups the Amendia segments (assess / enforce / closeout) of one ACH exposure case.",
        "close_schema": S.COHORT_CLOSE_SCHEMA,
        "close_correlation_path": "case_id",
        "close_outcome_path": "outcome",
    }
    headers = {"Authorization": f"Bearer {settings.registry_bearer}"}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(f"{settings.registry_url.rstrip('/')}/cohort/definitions", json=body, headers=headers)
        if resp.status_code == 201:
            logger.info("registered cohort definition '%s'", settings.cohort_def_id)
        elif resp.status_code == 409:
            logger.info("cohort definition '%s' already registered (idempotent)", settings.cohort_def_id)
        else:
            logger.warning("cohort registration returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:  # noqa: BLE001 — never block startup on this optional convenience
        logger.warning("cohort registration skipped (registry unreachable): %s", exc)
