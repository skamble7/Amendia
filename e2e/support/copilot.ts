// e2e/support/copilot.ts — helpers for the copilot LIFECYCLE journey (ach-copilot-lifecycle.spec.ts): things the
// deterministic driver did in Python but the copilot spec must do at RUNTIME, because the copilot infers pack
// structure per run (role names, human-artifact schemas, gate shapes all vary). Everything here reads the LIVE
// packs and adapts — it never hardcodes an inferred value.
//
// The crux is `synthesizeManualGateEdits`: a manual/human gate's output artifact carries a COPILOT-INFERRED JSON
// schema; we fetch it (ADR-060 pack-scoped) and synthesize a schema-valid instance, so the gate submits without a
// 422 (the de-risk's blocker). See backend/docs/_build-reports/ach_copilot_derisk_findings.md.
import fs from "node:fs";
import path from "node:path";

import { CFG, E2E_DIR } from "./env";
import { mintToken } from "./backend";

export const CORPUS = path.resolve(E2E_DIR, "../backend/docs/methodology/worked-examples/ach_exposure");

// ── loose JSON-schema shape (only the keywords the ACH artifacts use) ──────────────────────────────────────────
export interface JsonSchema {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: unknown[];
  const?: unknown;
  default?: unknown;
  minimum?: number;
  minItems?: number;
  format?: string;
}

// ── priya (owner/admin) HTTP against a service base ────────────────────────────────────────────────────────────
async function priya(base: string, method: string, p: string, body?: unknown): Promise<{ status: number; json: any }> {
  const tok = await mintToken("priya");
  const r = await fetch(base + p, {
    method,
    headers: { Authorization: `Bearer ${tok}`, "content-type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let json: any = null;
  const raw = await r.text();
  if (raw.trim()) { try { json = JSON.parse(raw); } catch { json = { raw: raw.slice(0, 200) }; } }
  return { status: r.status, json };
}

// ── identity: resolve a persona's user id + grant a role (admin path — uses priya's token, no persona /me cache
//    poison; personas are already provisioned by the time the spec runs, so this is the always-applicable path) ──
const _uids = new Map<string, string | null>();
export async function personaUid(persona: string): Promise<string | null> {
  if (_uids.has(persona)) return _uids.get(persona)!;
  const { status, json } = await priya(CFG.identity, "GET", "/users");
  let uid: string | null = null;
  if (status === 200 && Array.isArray(json)) {
    uid = json.find((u: { email?: string }) => u.email === `${persona}@amendia.dev`)?.amendia_user_id ?? null;
  }
  _uids.set(persona, uid);
  return uid;
}

/** Grant one role to a persona (idempotent: 409 = already held). Returns true on success/already-held. */
export async function grantRole(persona: string, role: string): Promise<boolean> {
  const uid = await personaUid(persona);
  if (!uid) return false;
  const { status } = await priya(CFG.identity, "POST", `/users/${uid}/roles`, { role });
  return status < 300 || status === 409;
}

// ── read the gate roles a committed pack declares (copilot-named, per-run) ─────────────────────────────────────
interface Binding { element_id?: string; hitl?: { mode?: string; role?: string }; executor?: { role?: string } }
/** Every gate role the pack declares (any binding with a hitl gate mode) — the roles we must grant to drive it. */
export function packGateRoles(manifest: Record<string, unknown> | null): string[] {
  const bindings = (manifest?.bindings ?? []) as Binding[];
  const roles = new Set<string>();
  for (const b of bindings) {
    const mode = b.hitl?.mode;
    if (mode && mode !== "none") {
      const r = b.hitl?.role ?? b.executor?.role;
      if (r) roles.add(r);
    }
  }
  return [...roles].sort();
}

// ── cohort membership (read-after-write flaky → one PUT+GET-verify; the spec wraps this in expect.poll) ─────────
export async function putCohortMembership(packKey: string, cohortDefId: string, correlationKey: string): Promise<boolean> {
  await priya(CFG.registry, "PUT", `/packs/${packKey}/1.0.0/cohort-membership`,
    { cohort_def_id: cohortDefId, correlation_key: correlationKey });
  const { status, json } = await priya(CFG.registry, "GET", `/packs/${packKey}/1.0.0`);
  return status === 200 && json?.cohort_membership?.cohort_def_id === cohortDefId;
}

// ── cohort definition (over the CAPTURED copilot pack keys) ────────────────────────────────────────────────────
export async function cohortDefinitionExists(defId: string): Promise<boolean> {
  return (await priya(CFG.registry, "GET", `/cohort/definitions/${defId}`)).status === 200;
}

/** Create the cohort definition: __start__ → assess → enforce → closeout → __close__, with the enforce→closeout
 *  arrival SLA (deadline 8s / at_risk 4s / wall / external — the deterministic breach target). Nodes are the
 *  CAPTURED copilot pack keys. Close schema/paths come from the corpus wrapper. Returns the HTTP status. */
export async function createCohortDefinition(defId: string, nodes: [string, string, string]): Promise<number> {
  const wrapper = JSON.parse(fs.readFileSync(path.join(CORPUS, "schemas", "cohort.ach_exposure.close.schema.json"), "utf8"));
  const [assess, enforce, closeout] = nodes;
  const graph = {
    nodes: nodes.map((n) => ({ node_id: n, node_type: "expected" })),
    edges: [
      { from_node: "__start__", to_node: assess, split: "and" },
      { from_node: assess, to_node: enforce, split: "and" },
      { from_node: enforce, to_node: closeout, split: "and",
        sla: { anchor_moment: "completion", satisfy_moment: "arrival", deadline_seconds: 8, at_risk_seconds: 4, clock: "wall", owner: "external" } },
      { from_node: closeout, to_node: "__close__", split: "and" },
    ],
    end_to_end_sla: { deadline_seconds: 86400, at_risk_seconds: 64800, clock: "wall", owner: "shared" },
  };
  return (await priya(CFG.registry, "POST", "/cohort/definitions", {
    cohort_def_id: defId, display_name: "ACH exposure (copilot)", close_schema: wrapper.close_schema,
    close_correlation_path: wrapper.close_correlation_path, close_outcome_path: wrapper.close_outcome_path,
    expectation_graph: graph,
  })).status;
}

// ── the corpus trigger schema for a segment (the fidelity input the copilot derives its trigger from) ──────────
export function triggerSchema(file: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(path.join(CORPUS, "schemas", file), "utf8")).json_schema;
}

// ── HITL task detail (as priya) — to read a manual gate's editable output artifacts + their pinned schema refs ──
interface PayloadArtifact { name: string; schema?: string; data?: unknown; draft?: boolean; authored_by_human?: boolean }
interface TaskDetail { pack_key: string; pack_version: string; payload?: { artifacts?: PayloadArtifact[] } }
export async function taskDetail(taskId: string): Promise<TaskDetail | null> {
  const { status, json } = await priya(CFG.runtime, "GET", `/hitl-tasks/${taskId}`);
  return status === 200 ? (json as TaskDetail) : null;
}

/** Fetch a pinned artifact's COPILOT-INFERRED json schema (ADR-060 pack-scoped). `ref` = "art.x.y@1.0.0". */
export async function artifactSchema(packKey: string, packVersion: string, ref: string): Promise<JsonSchema | null> {
  const [key, rawVer] = ref.split("@");
  const version = (rawVer ?? "1.0.0").replace(/^[\^~]/, ""); // pinned ref may carry ^/~ — the endpoint wants concrete
  const { status, json } = await priya(CFG.registry, "GET",
    `/packs/${packKey}/${packVersion}/artifact-schemas/${key}/${version}`);
  return status === 200 ? ((json?.json_schema ?? null) as JsonSchema | null) : null;
}

// ── synthesize a schema-valid instance (fills required fields per type/enum; respects additionalProperties:false
//    by emitting only declared properties) — this is what makes a copilot-inferred manual gate submit without 422 ─
function stringFor(name: string, correlation: string, schema: JsonSchema): string {
  if (schema.format === "date-time") return "2025-01-01T00:00:00Z";
  if (/case[_-]?id|correlation/i.test(name)) return correlation; // chain case_id → the pega correlation
  return "e2e";
}

export function synthesize(schema: JsonSchema | undefined, correlation: string, name = ""): unknown {
  if (!schema || typeof schema !== "object") return stringFor(name, correlation, {});
  if (schema.const !== undefined) return schema.const;
  if (schema.default !== undefined) return schema.default;
  if (Array.isArray(schema.enum) && schema.enum.length) return schema.enum[0];
  const type = Array.isArray(schema.type) ? (schema.type.find((t) => t !== "null") ?? schema.type[0]) : schema.type;
  switch (type) {
    case "object": {
      const out: Record<string, unknown> = {};
      const props = schema.properties ?? {};
      const required = new Set(schema.required ?? []);
      for (const [k, sub] of Object.entries(props)) {
        if (required.has(k) || sub.default !== undefined) out[k] = synthesize(sub, correlation, k);
      }
      for (const k of required) if (!(k in out)) out[k] = stringFor(k, correlation, {});
      return out;
    }
    case "array": {
      const min = schema.minItems ?? 0;
      return min > 0 ? Array.from({ length: min }, () => synthesize(schema.items, correlation)) : [];
    }
    case "boolean": return true;                 // approve / authorize path
    case "integer":
    case "number": return schema.minimum ?? 0;
    case "string":
    default: return stringFor(name, correlation, schema);
  }
}

/** For a manual gate task: read its editable (human-authored) output artifacts, fetch each one's inferred schema,
 *  and synthesize a valid value. Returns `{ artifactName: value }` (empty when the gate has no editable output —
 *  e.g. an approve_actions gate that only needs "Authorize"). */
export async function synthesizeManualGateEdits(taskId: string, correlation: string): Promise<Record<string, unknown>> {
  const detail = await taskDetail(taskId);
  const edits: Record<string, unknown> = {};
  for (const a of detail?.payload?.artifacts ?? []) {
    const editable = a.draft === true || a.authored_by_human === true;
    if (!editable || !a.schema) continue;
    const schema = await artifactSchema(detail!.pack_key, detail!.pack_version, a.schema);
    edits[a.name] = synthesize(schema ?? undefined, correlation, a.name);
  }
  return edits;
}
