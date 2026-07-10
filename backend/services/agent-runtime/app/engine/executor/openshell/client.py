# app/engine/executor/openshell/client.py
"""The OpenShell client interface + a deterministic fake and an HTTP scaffold.

``SandboxedExecutor`` (ADR-017) never talks to the sandbox directly — it builds a
``CapabilityRunSpec`` and hands it to an ``OpenShellClient``. Two implementations:

  * ``FakeOpenShellClient`` — no network; executes the SAME capability logic the
    in-process path would (simulation skills, or the shared ``run_real_llm`` primitive),
    returning schema-valid artifacts and a synthetic ``otlp_trace_id``. This proves the
    seam end-to-end and runs in CI with no gateway.
  * ``HttpOpenShellClient`` — a scaffold that would talk to a live NemoClaw gateway. Its
    wire details are unverified and marked ``# [confirm]``; it is not exercised in Phase 1.

**Security invariant (ADR-017 §7):** the spec carries a model-config *ref*
(``model_config_ref``) and schema/policy *handles* — never a raw provider key. Real
secrets stay host-side (in the gateway); the sandbox path sees only references.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.capabilities.wire_repair import SIM_CAPABILITIES
from app.engine.executor.base import CapabilityError
from app.engine.executor.dispatch import run_real_llm


@dataclass
class CapabilityRunSpec:
    """Everything a sandbox needs to execute one capability — and nothing it shouldn't.

    Carries the capability id/kind, the pinned input artifacts, the declared output JSON
    schema(s), the selected model-config *ref* (not the key value), and an egress/tool
    policy handle. No raw secrets.
    """

    capability_id: str
    kind: str                                  # llm | mcp | skill
    inputs: Dict[str, Any]
    envelope: Dict[str, Any]
    output_schemas: Dict[str, Any] = field(default_factory=dict)   # artifact_key -> json schema
    mode: str = "execute"                      # execute | propose
    approved_action_ids: Optional[List[str]] = None
    model_config_ref: Optional[str] = None     # ConfigForge ref — a reference, never a secret
    element_id: Optional[str] = None
    simulation: bool = True
    # Phase 3: derived from already-declared contract data (mcp.server_key, rail endpoint,
    # inference proxy). A placeholder handle in Phase 1.
    egress_policy: Any = None


@dataclass
class SandboxResult:
    """What a sandboxed execution returns to the host: artifact JSON + audit metadata.

    ``outputs`` mirrors the in-process ``result["outputs"]`` (artifact_key -> data), so the
    host's existing ``_validate`` step consumes it unchanged. ``otlp_trace_id`` +
    provider/model feed the ``actor_log`` entry (ADR-017 §8.1).
    """

    outputs: Dict[str, Any]
    otlp_trace_id: str
    provider: Optional[str] = None
    model: Optional[str] = None
    proposed_actions: Optional[List[Dict[str, Any]]] = None
    log: Optional[str] = None


@runtime_checkable
class OpenShellClient(Protocol):
    async def run_capability(self, spec: CapabilityRunSpec) -> SandboxResult:
        """Execute one capability in a sandbox and return its artifact JSON + trace id."""
        ...

    async def ping(self) -> bool:
        """Startup reachability probe — drives fail-closed / fallback (ADR-017 §4.3)."""
        ...


# --------------------------------------------------------------------------- #
class FakeOpenShellClient:
    """Deterministic, in-process OpenShell stand-in — the CI/dev substrate for Phase 1.

    It does not sandbox anything; it executes the same capability logic the in-process
    path would, so ``native`` and ``nemoclaw``(fake) produce identical artifacts. Selected
    automatically when ``AGENTRT_OPENSHELL_URL`` is unset.
    """

    def __init__(self, *, simulation: bool = True) -> None:
        self._simulation = simulation
        self._n = 0

    async def ping(self) -> bool:
        return True

    async def run_capability(self, spec: CapabilityRunSpec) -> SandboxResult:
        self._n += 1
        trace = f"fake-otlp-{spec.element_id or spec.capability_id}-{self._n}"

        if spec.simulation or self._simulation:
            result = self._run_sim(spec)
            outputs = result.get("outputs", {}) or {}
            return SandboxResult(
                outputs=outputs, otlp_trace_id=trace,
                provider="openshell-sim", model=spec.capability_id,
                proposed_actions=result.get("proposed_actions"),
                log=result.get("log"),
            )

        # Real path — reuse the exact polyllm primitive the in-process executor uses, so
        # the fake is a faithful stand-in. (mcp has no real broker in Phase 1 → sim.)
        if spec.kind == "llm":
            targets = [(akey, spec.output_schemas.get(akey)) for akey in spec.output_schemas]
            produced, provider, model = run_real_llm(
                capability_id=spec.capability_id, targets=targets, ref=spec.model_config_ref,
                inputs=spec.inputs, envelope=spec.envelope,
            )
            return SandboxResult(outputs=produced, otlp_trace_id=trace, provider=provider, model=model)

        result = self._run_sim(spec)
        return SandboxResult(
            outputs=result.get("outputs", {}) or {}, otlp_trace_id=trace,
            provider="openshell-sim", model=spec.capability_id,
            proposed_actions=result.get("proposed_actions"), log=result.get("log"),
        )

    @staticmethod
    def _run_sim(spec: CapabilityRunSpec) -> Dict[str, Any]:
        fn = SIM_CAPABILITIES.get(spec.capability_id)
        if fn is None:
            raise CapabilityError(
                f"no simulation capability registered for {spec.capability_id}"
            )
        return fn(
            inputs=spec.inputs, envelope=spec.envelope,
            mode=spec.mode, approved_action_ids=spec.approved_action_ids,
        )


# --------------------------------------------------------------------------- #
class HttpOpenShellClient:
    """Scaffold for the live NemoClaw gateway. Wire details are UNVERIFIED — every request/
    response shape below is a placeholder to be confirmed against live NemoClaw docs and is
    not exercised in Phase 1 (the fake covers CI). Constructing it is cheap; ``ping`` and
    ``run_capability`` will raise/deny until the wire format is confirmed.
    """

    def __init__(self, base_url: str, *, pool_size: int = 4, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._pool_size = pool_size
        self._timeout = timeout
        # Phase 3/5: warm-sandbox pool (AGENTRT_SANDBOX_POOL_SIZE); snapshot/rebuild.
        # [confirm] OpenShell sandbox lifecycle + pool semantics against live docs.

    async def ping(self) -> bool:
        # [confirm] gateway health endpoint against live NemoClaw docs.
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                resp = await http.get(f"{self._base_url}/healthz")
            return resp.status_code == 200
        except Exception:
            return False

    async def run_capability(self, spec: CapabilityRunSpec) -> SandboxResult:
        # [confirm] against live NemoClaw docs — gateway execute endpoint, request/response
        # shape, managed inference proxy path (inference.local/v1), OTLP trace id field, and
        # how per-sandbox egress policy + scoped credential placeholders are expressed.
        raise NotImplementedError(
            "HttpOpenShellClient is a Phase-1 scaffold; the live NemoClaw gateway wire "
            "format is unconfirmed. Leave AGENTRT_OPENSHELL_URL unset to use the fake."
        )
