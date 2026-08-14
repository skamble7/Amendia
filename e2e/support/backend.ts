// e2e/support/backend.ts — thin backend helpers the e2e legitimately uses OUTSIDE the browser: readiness,
// token mint (for a driver bearer / pack preflight), the trigger drivers (the external orchestrator/stub is
// genuinely not part of the webui), and the onboarded-pack check. Everything a USER does stays in the browser.
import { CFG, coreHealth, tokenUrl } from "./env";
import type { Scenario } from "./scenarios";

async function reachable(url: string): Promise<boolean> {
  try {
    await fetch(url, { signal: AbortSignal.timeout(4000) });
    return true;
  } catch {
    return false;
  }
}

export async function stackDownReason(): Promise<string | null> {
  const down: string[] = [];
  for (const [name, url] of Object.entries(coreHealth())) {
    if (!(await reachable(url))) down.push(name);
  }
  if (!down.length) return null;
  return `stack not reachable (${down.join(", ")} down) — bring it up: ` +
    "`docker compose -f backend/deploy/docker-compose.yml up -d` (+ pega_stub compose for ACH)";
}

const _tokens = new Map<string, string>();
export async function mintToken(persona: string): Promise<string> {
  if (_tokens.has(persona)) return _tokens.get(persona)!;
  const r = await fetch(tokenUrl(), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "password", client_id: CFG.cliClient, client_secret: CFG.cliSecret,
      username: persona, password: CFG.devPassword, scope: "openid",
    }),
  });
  if (!r.ok) throw new Error(`token mint failed for ${persona}: HTTP ${r.status}`);
  const tok = (await r.json()).access_token as string;
  _tokens.set(persona, tok);
  return tok;
}

export async function activePackKeys(): Promise<Set<string> | null> {
  try {
    const tok = await mintToken("priya");
    const r = await fetch(`${CFG.registry}/packs?status=active&limit=200`, {
      headers: { Authorization: `Bearer ${tok}` },
    });
    if (!r.ok) return null;
    return new Set((await r.json()).map((p: { pack_key: string }) => p.pack_key));
  } catch {
    return null;
  }
}

export async function missingPacks(sc: Scenario): Promise<string[] | null> {
  const active = await activePackKeys();
  if (active === null) return null; // couldn't read → let the caller decide
  return sc.pack_keys.filter((k) => !active.has(k));
}

let _caseSeq = 0;

// --- read helpers used only to DISCOVER which gate to open (the claim/decide/form is done in the browser) ---
async function authed(url: string): Promise<unknown | null> {
  try {
    const tok = await mintToken("priya");
    const r = await fetch(url, { headers: { Authorization: `Bearer ${tok}` } });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export async function cohortByCorrelation(value: string): Promise<{ state?: string; outcome?: string; roster?: { process_instance_id: string }[]; rollup?: { failed?: number } } | null> {
  return authed(`${CFG.glea}/cohorts/by-correlation/${value}`) as Promise<never>;
}

export async function instanceStatus(pid: string): Promise<string | null> {
  const d = (await authed(`${CFG.runtime}/instances/${pid}`)) as { status?: string } | null;
  return d?.status ?? null;
}

interface OpenTask { task_id: string; element_id: string; role: string; excluded: string[] }
/** The open HITL task on an instance (id + element + role + SoD excluded users) — so the browser can open
 * /inbox/<taskId> as a persona who is NOT SoD-excluded. */
export async function openTaskOn(pid: string): Promise<OpenTask | null> {
  const list = (await authed(`${CFG.runtime}/hitl-tasks?status=open&process_instance_id=${pid}`)) as
    { task_id: string; element_id: string; role?: string; sod?: { excluded_users?: string[] } }[] | null;
  if (!list || !list.length) return null;
  const t = list[0];
  return { task_id: t.task_id, element_id: t.element_id, role: t.role ?? "", excluded: t.sod?.excluded_users ?? [] };
}

/** A closed cohort's correlation value (for the member-diagram highlight journey), if any exist. */
export async function closedCohortCorrelation(): Promise<string | null> {
  const d = (await authed(`${CFG.glea}/cohorts?state=closed`)) as { cohorts?: { correlation_value: string }[] } | null;
  const c = d?.cohorts?.find((x) => x.correlation_value);
  return c?.correlation_value ?? null;
}

const _userIds = new Map<string, string | null>();
/** A persona's Amendia user id (for SoD exclusion checks) via identity /me. */
export async function personaUserId(persona: string): Promise<string | null> {
  if (_userIds.has(persona)) return _userIds.get(persona)!;
  const tok = await mintToken(persona).catch(() => null);
  let uid: string | null = null;
  if (tok) {
    try {
      const r = await fetch(`${CFG.identity}/me`, { headers: { Authorization: `Bearer ${tok}` } });
      if (r.ok) uid = (await r.json()).amendia_user_id ?? null;
    } catch { /* ignore */ }
  }
  _userIds.set(persona, uid);
  return uid;
}

/** Pick a persona from the pool who is NOT SoD-excluded for a task (mirrors the pytest resolver). */
export async function personaForTask(pool: string[], excluded: string[]): Promise<string> {
  const ex = new Set(excluded);
  for (const p of pool) {
    if (!ex.has((await personaUserId(p)) ?? "")) return p;
  }
  return pool[0]!;
}

/** Fire the scenario's real trigger (drivers keyed by kind), returning the correlation value. */
export async function fireScenario(sc: Scenario): Promise<string> {
  const kind = sc.trigger.kind;
  if (kind === "pega_stub") {
    // Tag the case with the run id so the run's fired cohorts are identifiable (teardown/reset note).
    const { RUN_ID } = await import("./setup");
    const caseId = `${RUN_ID}-${++_caseSeq}`;
    const r = await fetch(`${CFG.pegaStub}/cases`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...(sc.trigger.request ?? {}), case_id: caseId }),
    });
    if (!r.ok) throw new Error(`pega_stub POST /cases → ${r.status}`);
    const c = await r.json();
    const corr = c[sc.correlation] ?? c.case_id;
    if (!corr) throw new Error(`pega_stub case has no '${sc.correlation}'`);
    return String(corr);
  }
  if (kind === "stub_generator") {
    const req = (sc.trigger.request ?? {}) as { generator?: string; body?: Record<string, unknown> };
    const tok = await mintToken(sc.hitl.default_persona ?? "riya");
    const r = await fetch(`${CFG.stub}/generators/${req.generator}/generate`, {
      method: "POST", headers: { "content-type": "application/json", Authorization: `Bearer ${tok}` },
      body: JSON.stringify(req.body ?? {}),
    });
    if (!r.ok) throw new Error(`stub /generators/${req.generator}/generate → ${r.status}`);
    return String((await r.json()).created[0].trigger.trigger_id);
  }
  throw new Error(`fireScenario: unsupported trigger.kind '${kind}'`);
}
