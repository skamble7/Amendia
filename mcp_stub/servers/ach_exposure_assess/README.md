# ach-exposure-assess-mcp

The **Assess** segment's MCP server for the ADR-063 ACH-exposure cohort worked example. Streamable HTTP at
`/mcp`, port **8075**, network alias `ach-assess-mcp` → `http://ach-assess-mcp:8075/mcp`.

Tools (this segment only, + the shared handback): `classify_exposure`, `get_client_risk_profile`,
`recommend_disposition`, `draft_underwriting_message`, `notify_pega`. Schemas/handlers are carried over verbatim
from the (now-removed) combined `ach_exposure` server. `notify_pega` POSTs the segment handback to `PEGA_STUB_URL`.

```
pip install -e '.[test]' && pytest
ach-exposure-assess-mcp     # serves on :8075
```
