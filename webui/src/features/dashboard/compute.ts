/**
 * Pure client-side aggregations for the Exception Command Center. These are the
 * heart of the dashboard's "no new backend" contract — every counter is derived
 * from the existing list endpoints here, so a dedicated stats endpoint would only
 * ever be a performance optimisation, never a correctness requirement.
 *
 * # backend-aggregation: a future GET /stats/pipeline could replace the N-list
 * fan-out these functions run over; the shapes below are what it would return.
 */
import type { StoredException, IngestionRecord, ProcessInstance, HitlTask } from "@/api/types";

/** True when `iso` falls on the same calendar day as `ref` (local time). */
export function isSameDay(iso: string | null | undefined, ref: Date): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return (
    d.getFullYear() === ref.getFullYear() &&
    d.getMonth() === ref.getMonth() &&
    d.getDate() === ref.getDate()
  );
}

export interface PipelineCounts {
  raised: number;
  ingested: number;
  dispatched: number;
  running: number;
  waiting: number;
  completed: number;
  failed: number;
  noProcess: number;
}

/**
 * "Today's pipeline" tile values, scoped to records created today:
 *   Raised     = #exceptions
 *   Ingested   = #ingestions
 *   Dispatched = ingestions status ∈ {dispatched, accepted}
 *   No process = ingestions status = no_process
 *   Running / Waiting / Completed / Failed = instances by status.
 */
export function pipelineCounts(
  exceptions: StoredException[],
  ingestions: IngestionRecord[],
  instances: ProcessInstance[],
  now: Date,
): PipelineCounts {
  const exToday = exceptions.filter((e) => isSameDay(e.created_at, now));
  const ingToday = ingestions.filter((i) => isSameDay(i.created_at, now));
  const instToday = instances.filter((i) => isSameDay(i.created_at, now));
  const instBy = (status: string) => instToday.filter((i) => i.status === status).length;
  return {
    raised: exToday.length,
    ingested: ingToday.length,
    dispatched: ingToday.filter((i) => i.status === "dispatched" || i.status === "accepted").length,
    noProcess: ingToday.filter((i) => i.status === "no_process").length,
    running: instBy("running"),
    waiting: instBy("waiting_hitl"),
    completed: instBy("completed"),
    failed: instBy("failed"),
  };
}

export interface WaitStats {
  count: number;
  avgSeconds: number | null;
  oldestSeconds: number | null;
}

/** Open-task queue depth plus avg/oldest wait, computed from `now − created_at`. */
export function waitStats(openTasks: HitlTask[], now: Date): WaitStats {
  const ages = openTasks
    .map((t) => (t.created_at ? (now.getTime() - new Date(t.created_at).getTime()) / 1000 : null))
    .filter((n): n is number => n != null && Number.isFinite(n) && n >= 0);
  if (ages.length === 0) return { count: openTasks.length, avgSeconds: null, oldestSeconds: null };
  const avg = ages.reduce((a, b) => a + b, 0) / ages.length;
  return { count: openTasks.length, avgSeconds: avg, oldestSeconds: Math.max(...ages) };
}

/** Tally reason codes across exceptions, sorted by frequency (desc). */
export function reasonTally(exceptions: StoredException[]): { code: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const ex of exceptions) {
    for (const code of ex.reason_codes ?? []) counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([code, count]) => ({ code, count }))
    .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
}

/** Compact duration, e.g. 580 → "9m 40s", 1860 → "31m", 3900 → "1h 5m". */
export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const remS = s % 60;
  if (m < 60) return remS ? `${m}m ${remS}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return remM ? `${h}h ${remM}m` : `${h}h`;
}
