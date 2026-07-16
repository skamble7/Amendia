# `mcp_stub/` — standalone deterministic MCP servers

Standalone, deterministic ("dumb") MCP servers that expose the tools backing Amendia process
packs' capabilities. They return canned, **schema-valid** data — no real payment logic — so we
can test the **integration** end to end:

1. the process-registry onboarding wizard introspects a server
   (`POST /capabilities/introspect-mcp`, ADR-025) and turns each tool into an `mcp` capability +
   two artifact schemas;
2. the pack is driven to `active`;
3. the agent-runtime invokes the tools during a run (it reads `result.structuredContent`).

These are **not** Amendia services — they're a separate deliverable, a sibling of `backend/`,
`webui/`, `libs/`, `deploy/`.

## Layout

```
mcp_stub/
├── deploy/
│   └── docker-compose.yml          # deploys the server(s) in servers/ on the backend network
└── servers/
    └── wire_transfer_exception/    # one folder per authored server (add siblings for more)
        ├── pyproject.toml
        ├── Dockerfile
        ├── src/wire_transfer_exception_mcp/
        │   ├── schemas.py          # per-tool input/output JSON Schemas (the contract)
        │   ├── handlers.py         # dumb deterministic handlers + tool registry + compliance check
        │   ├── external.py         # deterministic external-system stand-ins (realism only)
        │   └── server.py           # streamable-HTTP MCP app (the 10 tools) + /health
        └── tests/test_server.py
```

## The server: `wire_transfer_exception`

Serves **streamable HTTP** at `/mcp` on port **8060** (env `PORT` / `MCP_PORT`, host `MCP_HOST`),
plus a `/health` route. No auth in dev (mirrors the existing stub-mcp). Exposes **ten
Amendia-MCP-compliant capability tools** — every tool declares `inputSchema` **and**
`outputSchema`; the three side-effectful action tools (`apply_repair`, `notify_parties`,
`execute_return`) return the guideline acknowledgement (`acknowledged` + `action_id` + `status`).
Outputs are fully closed, self-contained schemas; the `assess_beneficiary` output carries a
**required** `repair_verdict` because the pack's exclusive gateway branches on
`beneficiary.repair_verdict`.

Everything is deterministic: same input → same output (including `action_id`, a hash of
`exception_id` + tool name). Handlers echo salient input fields so a human reviewing a HITL task
sees plausible, connected data. `assess_beneficiary` / `screen_party` are steerable via input
(`repair_hint` / `reason_codes`, `hint` / creditor name) so a demo can drive each gateway branch.

`handlers.py` runs a **compliance self-check at import** (the exact rules the wizard enforces in
`process-registry/app/services/mcp_introspect.py`), so the server refuses to start if a tool ever
drifts out of compliance.

## Run it (Docker, on the shared backend network)

The registry/runtime resolve the server by the network alias **`wirefix-mcp`**, so this server
must join the **same Docker network** as the backend stack.

```bash
# 1) backend stack first (creates the shared network)
docker compose -f backend/deploy/docker-compose.yml up -d --build

# 2) the MCP stub(s)
docker compose -f mcp_stub/deploy/docker-compose.yml up --build
```

The onboarding wizard then introspects **`http://wirefix-mcp:8060/mcp`** (the exact endpoint) and
drives `wire-repair-agentic` to `active`.

**Shared network name.** The backend compose defines no explicit network, so its default is
`deploy_default` (Compose derives the project name from the compose file's directory,
`backend/deploy`). The stub compose references it as an **external** network defaulting to
`deploy_default`. If you brought the backend up under a different project name (e.g. `-p amendia`
→ `amendia_default`), override it:

```bash
AMENDIA_NETWORK=amendia_default docker compose -f mcp_stub/deploy/docker-compose.yml up --build
```

From the host, the server is also published on `localhost:8060` (health: `curl localhost:8060/health`).

## Tests

```bash
cd mcp_stub/servers/wire_transfer_exception
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest -q
```

Covers: exactly ten tools, the compliance self-check, every tool's output validated against its
declared `outputSchema` (draft 2020-12), `assess_beneficiary` producing all three verdicts, the
three action acks, determinism, and — via the `mcp` SDK's in-memory transport — `tools/list`
returning ten tools with both schemas and a structured `tools/call`.

## Adding another server

Create `servers/<name>/` with the same shape (`pyproject.toml`, `Dockerfile`,
`src/<pkg>/{schemas,handlers,server}.py`, `tests/`), then add a service block in
`deploy/docker-compose.yml` reusing the `amendia` external network and the streamable-HTTP
pattern (give it its own port and network alias). Do not fold multiple servers into one folder.
