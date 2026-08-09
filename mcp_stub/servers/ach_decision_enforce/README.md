# ach-decision-enforce-mcp

The **Enforce** segment's MCP server for the ADR-063 ACH-exposure cohort worked example. Streamable HTTP at
`/mcp`, port **8076**, network alias `ach-enforce-mcp` → `http://ach-enforce-mcp:8076/mcp`.

Tools (this segment only, + the shared handback): `capture_decision`, `prepare_release`, `request_purge`,
`notify_pega`. `capture_decision.rbo_decision` (enum approve/reject) is the Segment-B gateway key. Schemas/
handlers carried over verbatim from the (removed) combined `ach_exposure` server.

```
pip install -e '.[test]' && pytest
ach-decision-enforce-mcp     # serves on :8076
```
