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

/** Shorten a long id (UETR, exception id) for dense display, keeping head+tail. */
export function shortId(id: string | null | undefined, head = 8, tail = 4): string {
  if (!id) return "—";
  if (id.length <= head + tail + 1) return id;
  return `${id.slice(0, head)}…${id.slice(-tail)}`;
}
