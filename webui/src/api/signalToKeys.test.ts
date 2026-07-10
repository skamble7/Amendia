import { describe, it, expect } from "vitest";
import { signalToKeys, LIVE_KEYS } from "@/api/signalToKeys";

describe("signalToKeys", () => {
  it("hitl_task_created → task + instance + list keys", () => {
    const keys = signalToKeys({
      type: "hitl_task_created", task_id: "t1", process_instance_id: "pi1", exception_id: "e1",
    });
    expect(keys).toContainEqual(["hitl-tasks"]);
    expect(keys).toContainEqual(["hitl-task", "t1"]);
    expect(keys).toContainEqual(["instances"]);
    expect(keys).toContainEqual(["instance", "pi1"]);
    expect(keys).toContainEqual(["exception", "e1"]);
  });

  it("hitl_task_decided behaves the same as created", () => {
    const keys = signalToKeys({ type: "hitl_task_decided", task_id: "t9", process_instance_id: "pi9" });
    expect(keys).toContainEqual(["hitl-task", "t9"]);
    expect(keys).toContainEqual(["instance", "pi9"]);
  });

  it("process_completed → instance + lists, no task-scoped key", () => {
    const keys = signalToKeys({ type: "process_completed", process_instance_id: "pi2", outcome: "End_Resolved" });
    expect(keys).toContainEqual(["instances"]);
    expect(keys).toContainEqual(["instance", "pi2"]);
    expect(keys).toContainEqual(["hitl-tasks"]);
    expect(keys.some((k) => k[0] === "hitl-task")).toBe(false);
  });

  it("exception_dispatched → exception/ingestion pipeline keys", () => {
    const keys = signalToKeys({ type: "exception_dispatched", exception_id: "EXC-1" });
    expect(keys).toContainEqual(["ingestions"]);
    expect(keys).toContainEqual(["instances"]);
    expect(keys).toContainEqual(["exception", "EXC-1"]);
  });

  it("resync → every live key", () => {
    expect(signalToKeys({ type: "resync" })).toEqual(LIVE_KEYS);
  });

  it("unknown type → no keys", () => {
    expect(signalToKeys({ type: "not_a_real_event" })).toEqual([]);
  });

  it("omits id-scoped keys when ids are absent", () => {
    expect(signalToKeys({ type: "hitl_task_created" })).toEqual([["hitl-tasks"], ["instances"]]);
  });
});
