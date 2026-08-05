import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { SERVICE_BASE } from "@/api/config";

/**
 * MSW server for component tests only (MSW is a devDependency and never ships in
 * the app bundle). Tests register their own per-test handlers via `server.use(...)`
 * with small, obviously-synthetic values — see src/test/fixtures.ts.
 *
 * The one default handler is the roles-in-use catalog (`GET registry/roles`): the admin
 * role dialogs load it on mount to build their assignable-role list, so every dialog test
 * would otherwise have to stub it. It returns the two seed pack roles; a test can override
 * it with `server.use(...)` to assert a specific pack's roles surface. Any *other* un-stubbed
 * request still bypasses to a (failing) real fetch, so a missing stub stays visible.
 */
export const server = setupServer(
  http.get(`${SERVICE_BASE.registry}/roles`, () =>
    HttpResponse.json([
      { role_id: "role.payments.ops_analyst", label: "Analyst", description: "Reviews screening hits.", sources: ["wire-repair-standard@1.0.0"] },
      { role_id: "role.payments.ops_approver", label: "Approver", description: "Approves payment actions.", sources: ["wire-repair-standard@1.0.0"] },
    ]),
  ),
  // The role dialogs also fetch active packs to label the master-detail rail by title.
  // Default to empty (rail falls back to the pack_key from each role's sources); a test can
  // override to supply titles.
  http.get(`${SERVICE_BASE.registry}/packs`, () => HttpResponse.json([])),

  // ADR-058 Phase E: the instance page fetches the GLEA read-models on mount. Default them to
  // empty/zeroed so instance tests that don't care about GLEA don't hit unstubbed requests; a
  // GLEA test overrides these with data (or `HttpResponse.error()` for the glea-down fallback).
  http.get(`${SERVICE_BASE.glea}/audit/instances/:cid`, ({ params }) =>
    HttpResponse.json({ correlation_id: String(params.cid), count: 0, events: [] }),
  ),
  http.get(`${SERVICE_BASE.glea}/audit/instances/:cid/decision-trail`, ({ params }) =>
    HttpResponse.json({ correlation_id: String(params.cid), count: 0, gates: [] }),
  ),
  http.get(`${SERVICE_BASE.glea}/audit/instances/:cid/lineage`, ({ params }) =>
    HttpResponse.json({ correlation_id: String(params.cid), trace_id: "", nodes: [], edges: [] }),
  ),
  http.get(`${SERVICE_BASE.glea}/audit/instances/:cid/metrics`, ({ params }) =>
    HttpResponse.json({
      correlation_id: String(params.cid),
      approval_latency_ms: { p50: 0, p95: 0, count: 0 },
      capability_duration_ms: { p50: 0, p95: 0, count: 0 },
      hitl_decisions: [],
      four_eyes_enforced: 0,
      egress_denied: 0,
      sla_breaches: 0,
      instances_by_outcome: null,
    }),
  ),
  http.get(`${SERVICE_BASE.glea}/audit/instances/:cid/trace`, ({ params }) =>
    HttpResponse.json({ correlation_id: String(params.cid), trace_id: "", spans: [] }),
  ),
);
