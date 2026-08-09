# ach-closeout-mcp

The **Closeout** segment's MCP server for the ADR-063 ACH-exposure cohort worked example. Streamable HTTP at
`/mcp`, port **8077**, network alias `ach-closeout-mcp` → `http://ach-closeout-mcp:8077/mcp`.

Tools (this segment only, + the shared handback): `verify_disposition`, `mark_completed`, `purge_working_data`,
`notify_pega`. Schemas/handlers carried over verbatim from the (removed) combined `ach_exposure` server.

```
pip install -e '.[test]' && pytest
ach-closeout-mcp     # serves on :8077
```
