/**
 * Minimal, obviously-synthetic fixtures for component tests. These are NOT the
 * product demo scenario — deliberately fake ids/names/amounts so tests read as
 * tests. Build only what a given test asserts on.
 */
import type { HitlTask, InstanceDetail, StoredException } from "@/api/types";

export const TEST_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["verdict", "note"],
  properties: {
    verdict: { type: "string", enum: ["ok", "not_ok"] },
    note: { type: "string" },
  },
};

export function synthTask(overrides: Partial<HitlTask> = {}): HitlTask {
  return {
    task_id: "task-test-1",
    process_instance_id: "PI-TEST-1",
    pack_key: "test-pack",
    pack_version: "1.0.0",
    element_id: "Task_Test",
    exception_id: "EXC-TEST-001",
    hitl_mode: "review_after",
    role: "role.payments.ops_analyst",
    title: "Test gate",
    description: "A synthetic gate for tests.",
    priority: "normal",
    due_at: "2099-01-01T00:00:00Z",
    assignee: null,
    sod: null,
    payload: {
      artifacts: [{ name: "thing", schema: "art.test.thing@1.0.0", data: { verdict: "ok", note: "synthetic" } }],
      proposed_actions: null,
      context_url: "/instances/PI-TEST-1",
    },
    allowed_decisions: ["approve", "edit_and_approve", "reject"],
    status: "open",
    decision: null,
    created_at: "2099-01-01T00:00:00Z",
    updated_at: "2099-01-01T00:00:00Z",
    ...overrides,
  } as HitlTask;
}

export function synthInstanceDetail(overrides: Partial<InstanceDetail> = {}): InstanceDetail {
  return {
    instance: {
      process_instance_id: "PI-TEST-1",
      exception_id: "EXC-TEST-001",
      pack_key: "test-pack",
      pack_version: "1.0.0",
      status: "completed",
      correlation_id: "EXC-TEST-001",
      idempotency_key: "k",
      outcome: "End_Test",
      last_error: null,
      artifact_names: ["thing"],
      created_at: "2099-01-01T00:00:00Z",
      updated_at: "2099-01-01T00:00:00Z",
    } as InstanceDetail["instance"],
    status: "completed",
    outcome: "End_Test",
    artifact_names: ["thing"],
    actor_log: [
      { element_id: "Task_Test", actor: "cap.test.do", kind: "capability", at: "2099-01-01T00:00:00Z" },
      { element_id: "Task_Test", actor: "tester-1", kind: "human", at: "2099-01-01T00:00:01Z" },
    ],
    hitl_tasks: [],
    ...overrides,
  };
}

export function synthException(overrides: Partial<StoredException> = {}): StoredException {
  return {
    exception_id: "EXC-TEST-001",
    exception_type: "unable_to_apply",
    reason_codes: ["AC01"],
    reason_narrative: "Synthetic test exception",
    status: "open",
    payment: {
      msg_type: "pacs.008.001.10",
      uetr: "test-uetr-0001",
      settlement_amount: { currency: "USD", value: 100 },
      debtor: { name: "Test Debtor Ltd", account: null },
      creditor: { name: "Test Creditor Ltd", account: { id: "TESTIBAN00", scheme: "IBAN" } },
    },
    attachments: [],
    related_messages: [],
    ...overrides,
  } as unknown as StoredException;
}

export const synthPack = {
  manifest_version: "1.0",
  pack_key: "test-pack",
  version: "1.0.0",
  title: "Test Pack",
  status: "active",
  bindings: [{ element_id: "Task_Test", element_kind: "serviceTask", executor: { type: "capability", capability: "cap.test.do" }, hitl: { mode: "review_after", role: "role.payments.ops_analyst" }, inputs: [], outputs: [] }],
  triage_rules: [{ rule_id: "r1", priority: 100, when: { field: "reason_codes", op: "intersects", value: ["AC01"] } }],
  requires_capabilities: [],
  artifacts: [],
};

// --- GLEA read-model fixtures (ADR-058 Phase E) — obviously-synthetic. ---
export function synthDecisionTrail() {
  return {
    correlation_id: "EXC-TEST-001",
    count: 1,
    gates: [
      {
        element_id: "Task_Test",
        decided_by: "tester-1",
        role: "role.payments.ops_approver",
        decided_at: "2099-01-01T00:00:05Z",
        decision: "approve",
        sod_satisfied: true,
        comment: "synthetic approval note",
        proposed: { artifact_key: "art.test.thing", schema_ref: "art.test.thing@1.0.0" },
        approved: { artifact_key: "art.test.thing", schema_ref: "art.test.thing@1.0.0" },
      },
    ],
  };
}

export function synthLineage() {
  return {
    correlation_id: "EXC-TEST-001",
    trace_id: "abc123",
    nodes: [
      { span_id: "s1", element_id: "Task_A", artifact_key: "art.test.a", schema_ref: "art.test.a@1.0.0", actor_kind: "capability", authored_by_human: false },
      { span_id: "s2", element_id: "Task_B", artifact_key: "art.test.b", schema_ref: "art.test.b@1.0.0", actor_kind: "human", authored_by_human: true },
    ],
    edges: [{ from_span: "s1", to_span: "s2", from_artifact_key: "art.test.a", to_artifact_key: "art.test.b" }],
  };
}

export function synthMetrics() {
  return {
    correlation_id: "EXC-TEST-001",
    approval_latency_ms: { p50: 1200, p95: 4800, count: 2 },
    capability_duration_ms: { p50: 12, p95: 40, count: 3 },
    hitl_decisions: [{ decision: "approve", role: "role.payments.ops_approver", count: 1 }],
    four_eyes_enforced: 1,
    egress_denied: 0,
    sla_breaches: 0,
    instances_by_outcome: null,
  };
}

export function synthTraceTree() {
  return {
    correlation_id: "EXC-TEST-001",
    trace_id: "abc123",
    spans: [
      { span_id: "root", parent_span_id: "", name: "instance", start_ns: 0, duration_ns: 100, depth: 0, element_id: "", actor: "", actor_kind: "", artifact_key: "" },
      { span_id: "a", parent_span_id: "root", name: "Task_Test", start_ns: 10, duration_ns: 30, depth: 1, element_id: "Task_Test", actor: "cap.test.do", actor_kind: "capability", artifact_key: "art.test.thing" },
    ],
  };
}

export function synthInstanceAudit() {
  return {
    correlation_id: "EXC-TEST-001",
    count: 2,
    events: [
      { event_id: "e1", occurred_at: "2099-01-01T00:00:00Z", kind: "dispatch_accepted", correlation_id: "EXC-TEST-001", trace_id: "abc123" },
      { event_id: "e2", occurred_at: "2099-01-01T00:00:03Z", kind: "artifact_committed", correlation_id: "EXC-TEST-001", trace_id: "abc123", element_id: "Task_Test", actor: "cap.test.do", actor_kind: "capability", schema_ref: "art.test.thing@1.0.0", payload: { rationale: "synthetic reasoning for the test artifact" } },
    ],
  };
}

export const synthValidationReport = {
  pack_key: "test-pack",
  pack_version: "1.0.0",
  findings: [
    { code: "test_side_effect_error", severity: "error", stage: 4, element_id: "Task_Test", path: "bindings[0]", message: "synthetic stage-4 error for tests" },
  ],
};
