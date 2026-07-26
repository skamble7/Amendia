# app/engine/executor/dispatch.py
"""The in-process capability executor (``native`` mode) + the real-LLM primitive.

``InProcessExecutor`` runs the shared execution core (`executor/core.py`) in-process, adding
only per-instance memoization (ADR-019). The kind-dispatch itself lives in the core so the
in-process path and the in-sandbox worker (ADR-020) share one implementation. This module
also owns ``run_real_llm`` — the provider-agnostic polyllm/ConfigForge primitive the core
calls for ``llm`` capabilities.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from amendia_contracts.capability import CapabilityDescriptor

from app.config import settings
from app.engine.executor.base import (
    CapabilityError,
    ExecutionContext,
    _run_blocking,
    business_error_from_object,
)
from app.engine.executor.core import execute_capability
from app.engine.executor.memo import memoized_execute

logger = logging.getLogger(__name__)

# One polyllm LLMClient per ConfigForge ref — the ModelProfile is fetched once and
# reused across capability invocations (the provider/model/keys live in ConfigForge).
_LLM_CLIENTS: Dict[str, Any] = {}


class InProcessExecutor:
    """Today's executor — ``native`` mode. Implements the ``Executor`` protocol.

    ``memo``/``memoize`` add per-instance capability memoization (ADR-019); both default to
    disabled so ``native`` stays byte-for-byte unless ``AGENTRT_MEMOIZE_CAPABILITIES`` is set.
    """

    def __init__(self, *, memo: Optional[Any] = None, memoize: bool = False,
                 mcp_client: Optional[Any] = None, deep_agent_runner: Optional[Any] = None,
                 stub_inference: bool = False, skill_impls: Optional[Dict[str, Any]] = None) -> None:
        self._memo = memo
        self._memoize = memoize
        # ADR-047 D2: a `{capability_id: callable}` map of skill doubles (dev/CI) so a structural pack runs
        # with the skill behavior in the fixture layer, not the platform image.
        self._skill_impls = skill_impls
        # ADR-047 D2: an optional in-process MCP client. When supplied, `mcp`-kind capabilities execute
        # through it (the real dispatch path with an in-process transport) instead of the simulation
        # fallback — so an MCP-backed pack runs end-to-end in-process without a live server. None keeps the
        # legacy native behavior (mcp → simulation skill).
        self._mcp_client = mcp_client
        # ADR-047 D2: a `deep_agent` runner (e.g. SchemaStubDeepAgentRunner) + a `stub_inference` flag that
        # make `llm`/`deep_agent` caps produce schema-valid stubs — a `SIM_CAPABILITIES`-free dev/CI fake.
        self._deep_agent_runner = deep_agent_runner
        self._stub_inference = stub_inference

    def execute(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        return memoized_execute(
            memo=self._memo, enabled=self._memoize, inputs=inputs, ctx=ctx,
            run=lambda: self._execute_uncached(descriptor, inputs, ctx),
        )

    def _execute_uncached(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        # One execution implementation (ADR-020). With no MCP client, `mcp` falls back to the simulation
        # skill exactly as before; with one injected, `mcp` brokers through it (ADR-047 D2).
        return execute_capability(descriptor, inputs, ctx, mcp_client=self._mcp_client,
                                  deep_agent_runner=self._deep_agent_runner,
                                  stub_inference=self._stub_inference, skill_impls=self._skill_impls)


# --------------------------------------------------------------------------- #
# Reusable real-LLM primitive (shared by InProcessExecutor and the OpenShell fake).
# The provider/model/keys live in ConfigForge and are addressed by ``ref`` only — a
# reference, never a raw secret — so this can be routed through a managed inference
# proxy later (ADR-017 §6, Phase 2) without changing callers.
# --------------------------------------------------------------------------- #
def run_real_llm(
    *, capability_id: str, targets, ref: str, inputs: Dict[str, Any], envelope: Dict[str, Any],
    error_codes: Optional[list] = None, cancel: Optional[Any] = None,
    title: Optional[str] = None, description: Optional[str] = None,
):
    """Prompt the configured model for one schema-constrained JSON object per target.

    ``targets`` is a list of ``(artifact_key, json_schema_or_None)``. Returns
    ``(produced, provider, model)`` where ``produced`` maps artifact_key → parsed dict.

    The system framing is **descriptor-sourced** and domain-neutral (ADR-047): the capability's role
    comes from its registered ``title``/``description`` and the artifact it must produce — the platform
    embeds no business-area noun. ``error_codes`` (ADR-035) are the legal error boundary codes for this
    element; when non-empty the model MAY, for a *modeled* failure, return
    ``{"business_error": {"code": "<one of the listed codes>", "detail": {...}}}`` instead of the artifact.
    Such a response is re-raised as a :class:`CapabilityBusinessError` (routed to the boundary); genuine
    LLM/transport failures and non-JSON output stay a technical :class:`CapabilityError`.
    """
    client = _llm_client(ref)
    codes = [c for c in (error_codes or []) if c]
    error_hint = (
        "\n\nIf — and ONLY if — a modeled business failure applies, you MAY instead return "
        '{"business_error": {"code": "<CODE>", "detail": {...}}} where <CODE> is EXACTLY one of: '
        f"{', '.join(codes)}. Otherwise return the artifact as instructed."
        if codes else ""
    )
    # Descriptor-sourced role clause — the domain (if any) lives in the registered title/description.
    role = f" — {title}" if title else ""
    role_desc = f" {description}" if description else ""
    produced: Dict[str, Any] = {}
    provider = model = None
    for artifact_key, schema in targets:
        # ADR-040: cooperative cancellation — bail between turns if the node's SLA deadline breached.
        if cancel is not None and cancel.cancelled:
            raise CapabilityError(f"{capability_id}: cancelled (SLA deadline) between LLM turns")
        schema_hint = (
            f"\n\nThe JSON object MUST validate against this JSON Schema:\n{json.dumps(schema)}"
            if schema else ""
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are the '{capability_id}' capability{role}.{role_desc} Produce a SINGLE "
                    f"JSON object for artifact '{artifact_key}'. Respond with JSON only — no markdown, "
                    f"no prose, no code fences.{schema_hint}{error_hint}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Trigger:\n{json.dumps(envelope, default=str)}\n\n"
                    f"Upstream artifacts (inputs):\n{json.dumps(inputs, default=str)}"
                ),
            },
        ]
        try:
            result = _run_blocking(client.chat(messages))
        except Exception as exc:  # noqa: BLE001 - surface as a capability failure
            raise CapabilityError(f"{capability_id}: LLM call failed: {exc}") from exc

        data = _parse_json(result.text)
        if data is None:
            raise CapabilityError(
                f"{capability_id}: LLM returned non-JSON for {artifact_key}: "
                f"{result.text[:200]!r}"
            )
        # ADR-035: a discriminated business_error object → modeled error (routed to the boundary),
        # NOT the artifact. Raise before recording it as output.
        be = business_error_from_object(data)
        if be is not None:
            raise be
        produced[artifact_key] = data
        provider = result.raw.get("provider")
        model = result.raw.get("model")
    return produced, provider, model


def _llm_client(ref: str) -> Any:
    """Fetch (and cache) a polyllm LLMClient for a given ConfigForge ref."""
    client = _LLM_CLIENTS.get(ref)
    if client is None:
        try:
            from polyllm import RemoteConfigLoader
        except ImportError as exc:  # pragma: no cover - real path only
            raise CapabilityError(
                "real LLM path requires polyllm — install the service's LLM dependencies "
                "(or set AGENTRT_SIMULATION_MODE=true)"
            ) from exc
        loader = RemoteConfigLoader(base_url=settings.CONFIG_FORGE_URL)
        client = _run_blocking(loader.load(ref))
        _LLM_CLIENTS[ref] = client
        logger.info("loaded LLM profile '%s' from ConfigForge (%s)", ref, settings.CONFIG_FORGE_URL)
    return client


# --------------------------------------------------------------------------- #
def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse of a model response into a JSON object.

    polyllm already strips code fences for Bedrock ``json_mode``; this is a
    provider-agnostic safety net (fences / surrounding prose)."""
    text = (text or "").strip()
    if text.startswith("```"):
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("{"):
                text = part
                break
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            try:
                parsed = json.loads(text[i : j + 1])
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None
