# tests/_stub_stack.py
"""ADR-047 D2 — the SIM_CAPABILITIES-free execution stack for tests.

After the re-home, the seed packs are MCP-backed data. This is the executor tests use to run them in-process:
`mcp` → an in-process client wired to the wire-transfer server's own tools; `llm` → schema-stub; `deep_agent`
→ schema-stub runner; `decision`/`reduce` → native; `skill` → the structural fixture doubles (compose/scope/
event/payment packs). No per-process capability code in the platform image.
"""
from __future__ import annotations

from app.engine.executor import InProcessExecutor
from app.engine.executor.mcp_client import InProcessMcpClient
from app.engine.executor.stub_inference import SchemaStubDeepAgentRunner
from tests._mcp_server_tools import server_tool_map
from tests._structural_tools import STRUCTURAL_IMPLS


def _stub_mcp_client(tools=None):
    tmap = server_tool_map()
    if tools:
        tmap = {**tmap, **tools}
    return InProcessMcpClient(tmap)


def stub_executor(*, tools=None, **kw) -> InProcessExecutor:
    """The full D2 stub stack. ``tools`` overrides/extends the server tool map (e.g. an `isError` tool that
    injects a modeled business error — the MCP-native way to exercise error-boundary routing). Extra kwargs
    (memo/memoize) pass through."""
    return InProcessExecutor(
        mcp_client=_stub_mcp_client(tools),
        deep_agent_runner=SchemaStubDeepAgentRunner(),
        stub_inference=True,
        skill_impls=STRUCTURAL_IMPLS,
        **kw,
    )


def stub_run_job(job, *, tools=None, **kw):
    """The capability-worker counterpart of :func:`stub_executor`: runs ``run_job`` with the SAME injected
    stub stack (ADR-047 D2). The broker/worker path is transparent to the native path by construction."""
    from app.engine.executor.worker_runner import run_job
    return run_job(
        job,
        mcp_client=_stub_mcp_client(tools),
        deep_agent_runner=SchemaStubDeepAgentRunner(),
        stub_inference=True,
        skill_impls=STRUCTURAL_IMPLS,
        **kw,
    )


def stub_fake_client(*, tools=None, **kw):
    """The sandbox counterpart of :func:`stub_executor`: a ``FakeOpenShellClient`` wired to the SAME injected
    stub stack (ADR-047 D2). Because the sandbox spec carries the pinned descriptor, the fake runs the same
    ``execute_capability`` dispatch as the native path — native and nemoclaw(fake) are transparent by
    construction, with no parallel simulation implementation."""
    from app.engine.executor.openshell import FakeOpenShellClient
    return FakeOpenShellClient(
        mcp_client=_stub_mcp_client(tools),
        deep_agent_runner=SchemaStubDeepAgentRunner(),
        stub_inference=True,
        skill_impls=STRUCTURAL_IMPLS,
        **kw,
    )
