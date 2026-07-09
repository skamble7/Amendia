// Generates TypeScript types from each running service's OpenAPI document.
// Requires the compose stack (or the services) to be up. Commit the output.
//
//   pnpm gen:api          — regenerate src/api/gen/*.ts in place
//   pnpm gen:api:check     — fail (nonzero) if committed gen/ has drifted
//
// This module exports `generate(outDir)` + `SERVICES` so gen-api-check.mjs can
// regenerate into a temp dir and diff without duplicating the generation logic.
//
// The two agent-runtime instance-detail endpoints (GET /instances/{id} and
// /instances/{id}/state) have no FastAPI response_model, so their shapes are
// NOT emitted here — they are hand-written in src/api/services/runtime.ts and
// must be kept in sync with backend/services/agent-runtime/app/routers/instances.py.

import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import openapiTS, { astToString } from "openapi-typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const DEFAULT_OUT_DIR = path.resolve(__dirname, "../src/api/gen");

export const SERVICES = {
  stub: process.env.VITE_STUB_URL ?? "http://localhost:8081",
  ingestor: process.env.VITE_INGESTOR_URL ?? "http://localhost:8082",
  runtime: process.env.VITE_RUNTIME_URL ?? "http://localhost:8083",
  registry: process.env.VITE_REGISTRY_URL ?? "http://localhost:8084",
  identity: process.env.VITE_IDENTITY_URL ?? "http://localhost:8086",
};

// Env-independent header (no host URL) so the output is byte-stable across
// machines/ports — that stability is what makes `gen:api:check` a reliable gate.
function bannerFor(name) {
  return (
    `// GENERATED — DO NOT HAND-EDIT.\n` +
    `// Run \`pnpm gen:api\` to regenerate the ${name} types from its live OpenAPI document.\n` +
    `// \`pnpm gen:api:check\` fails when this file drifts from the running API.\n\n`
  );
}

/** Regenerate every service's types into `outDir`. Returns the failure count. */
export async function generate(outDir = DEFAULT_OUT_DIR) {
  await mkdir(outDir, { recursive: true });
  let failures = 0;
  for (const [name, base] of Object.entries(SERVICES)) {
    const url = `${base}/openapi.json`;
    try {
      const ast = await openapiTS(new URL(url));
      await writeFile(path.join(outDir, `${name}.ts`), bannerFor(name) + astToString(ast));
      console.log(`✓ ${name.padEnd(9)} ${url}`);
    } catch (err) {
      failures++;
      console.error(`✗ ${name.padEnd(9)} ${url}\n    ${err?.message ?? err}`);
    }
  }
  return failures;
}

// CLI entry (only when run directly, not when imported by the check script).
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const outDir = process.env.GEN_OUT_DIR ? path.resolve(process.env.GEN_OUT_DIR) : DEFAULT_OUT_DIR;
  const failures = await generate(outDir);
  if (failures > 0) {
    console.error(`\n${failures} service(s) unreachable. Is the compose stack up?`);
    process.exit(1);
  }
}
