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
);
