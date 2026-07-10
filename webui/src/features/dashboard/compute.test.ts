import { describe, it, expect } from "vitest";
import {
  isSameDay,
  pipelineCounts,
  waitStats,
  reasonTally,
  formatDuration,
} from "./compute";
import { formatActivitySignal } from "./activity";
import type { StoredException, IngestionRecord, ProcessInstance, HitlTask } from "@/api/types";
import type { Signal } from "@/api/notificationsStream";

const NOW = new Date("2026-07-08T12:00:00Z");
const today = (h = 9) => new Date(`2026-07-08T${String(h).padStart(2, "0")}:00:00Z`).toISOString();
const yesterday = new Date("2026-07-07T09:00:00Z").toISOString();

const ex = (over: Partial<StoredException>): StoredException =>
  ({ reason_codes: [], created_at: today(), ...over }) as unknown as StoredException;
const ing = (over: Partial<IngestionRecord>): IngestionRecord =>
  ({ status: "received", created_at: today(), ...over }) as unknown as IngestionRecord;
const inst = (over: Partial<ProcessInstance>): ProcessInstance =>
  ({ status: "running", created_at: today(), ...over }) as unknown as ProcessInstance;

describe("isSameDay", () => {
  it("matches same calendar day and rejects others", () => {
    expect(isSameDay(today(), NOW)).toBe(true);
    expect(isSameDay(yesterday, NOW)).toBe(false);
    expect(isSameDay(null, NOW)).toBe(false);
    expect(isSameDay("not-a-date", NOW)).toBe(false);
  });
});

describe("pipelineCounts", () => {
  it("tallies each stage from today's records only", () => {
    const exceptions = [ex({}), ex({}), ex({ created_at: yesterday })];
    const ingestions = [
      ing({ status: "received" }),
      ing({ status: "dispatched" }),
      ing({ status: "accepted" }),
      ing({ status: "no_process" }),
      ing({ status: "dispatched", created_at: yesterday }),
    ];
    const instances = [
      inst({ status: "running" }),
      inst({ status: "waiting_hitl" }),
      inst({ status: "completed" }),
      inst({ status: "completed" }),
      inst({ status: "failed" }),
      inst({ status: "completed", created_at: yesterday }),
    ];
    const c = pipelineCounts(exceptions, ingestions, instances, NOW);
    expect(c.raised).toBe(2);
    expect(c.ingested).toBe(4);
    expect(c.dispatched).toBe(2); // dispatched + accepted, today only
    expect(c.noProcess).toBe(1);
    expect(c.running).toBe(1);
    expect(c.waiting).toBe(1);
    expect(c.completed).toBe(2);
    expect(c.failed).toBe(1);
  });
});

describe("waitStats", () => {
  const task = (createdAt: string | null): HitlTask =>
    ({ created_at: createdAt } as unknown as HitlTask);

  it("computes avg and oldest from now − created_at", () => {
    // 10 min and 30 min old.
    const tasks = [
      task(new Date(NOW.getTime() - 10 * 60_000).toISOString()),
      task(new Date(NOW.getTime() - 30 * 60_000).toISOString()),
    ];
    const s = waitStats(tasks, NOW);
    expect(s.count).toBe(2);
    expect(s.avgSeconds).toBe(20 * 60);
    expect(s.oldestSeconds).toBe(30 * 60);
  });

  it("returns nulls (but keeps count) when no timestamps are usable", () => {
    const s = waitStats([task(null)], NOW);
    expect(s.count).toBe(1);
    expect(s.avgSeconds).toBeNull();
    expect(s.oldestSeconds).toBeNull();
  });
});

describe("reasonTally", () => {
  it("tallies reason codes across exceptions, sorted desc", () => {
    const exceptions = [
      ex({ reason_codes: ["AC01", "AC04"] }),
      ex({ reason_codes: ["AC01"] }),
      ex({ reason_codes: ["AC01", "BE04"] }),
    ];
    expect(reasonTally(exceptions)).toEqual([
      { code: "AC01", count: 3 },
      { code: "AC04", count: 1 },
      { code: "BE04", count: 1 },
    ]);
  });
});

describe("formatDuration", () => {
  it("formats seconds / minutes / hours compactly", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(580)).toBe("9m 40s");
    expect(formatDuration(1860)).toBe("31m");
    expect(formatDuration(3900)).toBe("1h 5m");
    expect(formatDuration(7200)).toBe("2h");
  });
});

describe("formatActivitySignal", () => {
  const cases: [Signal, string][] = [
    [{ type: "hitl_task_created", element_id: "Task_Review", role: "role.ops" }, "Task created — Task_Review (waiting on role.ops)"],
    [{ type: "hitl_task_decided", element_id: "Task_Review" }, "Decision recorded — Task_Review"],
    [{ type: "process_completed", outcome: "End_Resolved" }, "Instance completed — End_Resolved"],
    [{ type: "process_failed" }, "Instance failed"],
    [{ type: "dispatch_accepted", process_instance_id: "PI-42" }, "Dispatched — PI-42"],
    [{ type: "exception_raised", exception_id: "EXC-1" }, "Exception raised — EXC-1"],
    [{ type: "exception_dispatched", exception_id: "EXC-1" }, "Exception dispatched — EXC-1"],
  ];
  it.each(cases)("maps %o", (signal, expected) => {
    expect(formatActivitySignal(signal)).toBe(expected);
  });

  it("falls back to the raw type for unknown signals", () => {
    expect(formatActivitySignal({ type: "mystery" })).toBe("mystery");
  });
});
