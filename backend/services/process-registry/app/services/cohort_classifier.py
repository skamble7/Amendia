# app/services/cohort_classifier.py
"""ADR-063 Phase 2 — recognise an external end-of-process (close) message.

The registry owns cohort definitions + their close schemas, so it classifies inbound messages (folded into
``/resolve``). A message that validates against a registered ``close_schema`` AND yields a ``correlation_value``
via that definition's ``close_correlation_path`` is a close; otherwise it falls through to normal triage. Never
raises for a bad/foreign message — an unusable match is simply "no close" (fall through), never a 500.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from jsonschema import Draft202012Validator

from app.dal.cohort_def_repo import CohortDefinitionRepository

logger = logging.getLogger(__name__)


def dotget(obj: Any, path: Optional[str]) -> Optional[Any]:
    """Resolve a dotpath (``a.b.c``) into a nested dict; None when absent/untraversable or path is falsy."""
    if not path:
        return None
    node = obj
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class CohortClassifier:
    def __init__(self, repo: CohortDefinitionRepository) -> None:
        self._repo = repo

    async def classify(self, envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return ``{cohort_def_id, correlation_value, close_outcome}`` if ``envelope`` is a recognised close
        message, else None. Deterministic tie-break (sort by ``cohort_def_id``) if >1 schema matches — but since
        ``correlation_value`` alone resolves the instance, an ambiguous ``cohort_def_id`` is non-fatal (logged)."""
        matches = []
        for d in await self._repo.list():                      # repo.list() is already cohort_def_id-sorted
            try:
                if list(Draft202012Validator(d.close_schema).iter_errors(envelope)):
                    continue                                   # doesn't satisfy this close schema
            except Exception as exc:  # noqa: BLE001 - a malformed stored schema must not 500 a resolve
                logger.warning("cohort close schema for %s is invalid, skipping: %s", d.cohort_def_id, exc)
                continue
            value = dotget(envelope, d.close_correlation_path)
            if value is None or value == "":
                continue                                       # schema matched but no usable value → not a close
            matches.append((d, str(value)))

        if not matches:
            return None
        if len(matches) > 1:
            logger.warning("close message matched %d cohort definitions %s — using first by id (correlation_value "
                           "resolves the instance regardless)", len(matches), [d.cohort_def_id for d, _ in matches])
        definition, correlation_value = matches[0]
        outcome = dotget(envelope, definition.close_outcome_path)
        return {
            "cohort_def_id": definition.cohort_def_id,
            "correlation_value": correlation_value,
            "close_outcome": str(outcome) if outcome is not None else None,
        }
