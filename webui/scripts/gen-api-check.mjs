// Drift gate for the generated API types (CI-ready; not yet wired into a pipeline).
//
//   npm run gen:api:check
//
// Regenerates every service's types into a temp dir and compares them against the
// committed src/api/gen/*.ts. Exits nonzero if any file differs (i.e. someone
// hand-edited gen/, or the backend contract changed without a regenerate+commit),
// or if the stack isn't reachable. Zero diff == gen/ is 100% generator-owned.

import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { DEFAULT_OUT_DIR, SERVICES, generate } from "./gen-api.mjs";

const tmp = await mkdtemp(path.join(tmpdir(), "amendia-gen-check-"));
try {
  const failures = await generate(tmp);
  if (failures > 0) {
    console.error("\n✗ gen:api:check — service(s) unreachable. Bring the compose stack up first.");
    process.exit(1);
  }

  const drift = [];
  for (const name of Object.keys(SERVICES)) {
    const committed = await readFile(path.join(DEFAULT_OUT_DIR, `${name}.ts`), "utf8").catch(() => null);
    const fresh = await readFile(path.join(tmp, `${name}.ts`), "utf8");
    if (committed !== fresh) drift.push(name);
  }

  if (drift.length > 0) {
    console.error(`\n✗ gen/ is stale or hand-edited for: ${drift.join(", ")}`);
    console.error("  Run `npm run gen:api` and commit the result.");
    process.exit(1);
  }
  console.log("✓ gen/ is up to date with the live API (no drift).");
} finally {
  await rm(tmp, { recursive: true, force: true });
}
