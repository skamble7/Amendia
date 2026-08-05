import { formatDistanceToNowStrict, format, differenceInSeconds } from "date-fns";

/** Format a money amount with tabular grouping. Amounts are strings/numbers from the wire. */
export function formatMoney(amount: number | string | null | undefined, currency?: string | null): string {
  if (amount == null || amount === "") return "—";
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(n)) return String(amount);
  const formatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
  return currency ? `${currency} ${formatted}` : formatted;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return format(d, "d MMM yyyy, HH:mm");
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return formatDistanceToNowStrict(d, { addSuffix: true });
}

/** Countdown string for SLA (`due_at`); negative when overdue. */
export function formatCountdown(dueAt: string | null | undefined): { text: string; overdue: boolean } {
  if (!dueAt) return { text: "—", overdue: false };
  const d = new Date(dueAt);
  if (Number.isNaN(d.getTime())) return { text: String(dueAt), overdue: false };
  const secs = differenceInSeconds(d, new Date());
  const overdue = secs < 0;
  const abs = Math.abs(secs);
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const parts = h > 0 ? `${h}h ${m}m` : `${m}m`;
  return { text: overdue ? `${parts} overdue` : `${parts} left`, overdue };
}

/** Short wall-clock duration between two ISO timestamps (e.g. "3m 26s", "142ms", "1h 4m"). ``endIso``
 * absent → now (a running instance). Returns "—" on missing/invalid input. */
export function formatDurationShort(startIso: string | null | undefined, endIso?: string | null): string {
  if (!startIso) return "—";
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "—";
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

/** Shorten a long id (UETR, exception id) for dense display, keeping head+tail. */
export function shortId(id: string | null | undefined, head = 8, tail = 4): string {
  if (!id) return "—";
  if (id.length <= head + tail + 1) return id;
  return `${id.slice(0, head)}…${id.slice(-tail)}`;
}
