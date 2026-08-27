// e2e/support/scenarios.ts — reuse the pytest smoke's scenario specs (single source of "what scenario / expected
// outcome / which gate authors which artifact"). The Playwright suite drives the SAME scenarios through the UI.
import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";

import { SCENARIOS_DIR } from "./env";

export interface Scenario {
  domain: string;
  pack_keys: string[];
  trigger: { kind: string; request?: Record<string, unknown> };
  correlation: string;
  hitl: {
    default_persona?: string;
    roles?: Record<string, string>;
    personas?: string[];
    outputs?: Record<string, Record<string, unknown>>; // element_id -> artifact edits (interpolate {correlation})
  };
  expect: { instance_status?: string; cohort?: { state?: string; outcome?: string } };
  timeout_s?: number;
  skip?: boolean;
  skip_reason?: string;
}

export function loadScenarios(): Scenario[] {
  if (!fs.existsSync(SCENARIOS_DIR)) return [];
  return fs
    .readdirSync(SCENARIOS_DIR)
    .filter((f) => f.endsWith(".yaml"))
    .map((f) => yaml.load(fs.readFileSync(path.join(SCENARIOS_DIR, f), "utf8")) as Scenario)
    .filter(Boolean)
    .sort((a, b) => a.domain.localeCompare(b.domain));
}

export function scenario(domain: string): Scenario | undefined {
  return loadScenarios().find((s) => s.domain === domain);
}

/** Deep-fill `{correlation}` (and any context key) placeholders in a spec output template. */
export function interpolate<T>(value: T, ctx: Record<string, string>): T {
  if (typeof value === "string") {
    return value.replace(/\{(\w+)\}/g, (_, k) => (k in ctx ? ctx[k]! : `{${k}}`)) as unknown as T;
  }
  if (Array.isArray(value)) return value.map((v) => interpolate(v, ctx)) as unknown as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, interpolate(v, ctx)]),
    ) as T;
  }
  return value;
}
