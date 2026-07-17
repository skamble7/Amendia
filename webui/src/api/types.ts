/**
 * Convenience aliases over the generated OpenAPI types. Features import from
 * here, never re-declaring backend shapes. The only hand-written types are the
 * two agent-runtime instance-detail responses, which have no FastAPI
 * response_model (plain dicts) and therefore aren't in the generated output —
 * see InstanceDetail / InstanceState below.
 */
import type { components as RuntimeComponents } from "./gen/runtime";
import type { components as RegistryComponents } from "./gen/registry";
import type { components as IngestorComponents } from "./gen/ingestor";
import type { components as StubComponents } from "./gen/stub";

// --- agent-runtime (:8083) ---
export type HitlTask = RuntimeComponents["schemas"]["HitlTask"];
export type TaskPayload = RuntimeComponents["schemas"]["TaskPayload"];
export type PayloadArtifact = RuntimeComponents["schemas"]["PayloadArtifact"];
export type ProposedAction = RuntimeComponents["schemas"]["ProposedAction"];
export type Sod = RuntimeComponents["schemas"]["Sod"];
export type DecisionRecord = RuntimeComponents["schemas"]["DecisionRecord"];
export type DecideRequest = RuntimeComponents["schemas"]["DecideRequest"];
export type ProcessInstance = RuntimeComponents["schemas"]["ProcessInstance"];

// --- registry (:8084) + runtime read mirrors ---
// Pydantic models containing the Predicate union serialize differently for
// request vs response, so openapi-typescript splits them into -Input/-Output.
// The UI reads packs, so it uses the -Output (response) shapes.
export type ProcessPackManifest = RegistryComponents["schemas"]["ProcessPackManifest-Output"];
export type Binding = RegistryComponents["schemas"]["Binding"];
export type CapabilityDescriptor = RegistryComponents["schemas"]["CapabilityDescriptor"];
export type ArtifactSchemaRegistration = RegistryComponents["schemas"]["ArtifactSchemaRegistration"];
export type ResolveRequest = RegistryComponents["schemas"]["ResolveRequest"];
export type ResolveResponse = RegistryComponents["schemas"]["ResolveResponse"];
export type TriageRule = RegistryComponents["schemas"]["TriageRule-Output"];
export type RequiresCapability = RegistryComponents["schemas"]["RequiresCapability"];
export type GatewayVariable = RegistryComponents["schemas"]["GatewayVariable"];

// --- ingestor (:8082) ---
export type IngestionRecord = IngestorComponents["schemas"]["IngestionRecord"];
export type ResolutionRef = IngestorComponents["schemas"]["ResolutionRef"];
export type StatusChange = IngestorComponents["schemas"]["StatusChange"];

// --- stub (:8081) ---
export type StoredException = StubComponents["schemas"]["StoredException"];
export type GenerateRequest = StubComponents["schemas"]["GenerateRequest"];
export type GenerateResponse = StubComponents["schemas"]["GenerateResponse"];
export type Attachment = StubComponents["schemas"]["Attachment"];
export type PaymentDetails = StubComponents["schemas"]["PaymentDetails"];

// --- enums / literals we lean on across the UI (kept narrow, mirrors contracts) ---
export type InstanceStatus = "created" | "running" | "waiting_hitl" | "waiting_timer" | "waiting_message" | "completed" | "failed" | "cancelled";
export type IngestionStatus = "received" | "dispatched" | "accepted" | "rejected" | "no_process";

/**
 * GET /instances/{id} — NO backend response_model (plain dict).
 * Keep in sync with backend/services/agent-runtime/app/routers/instances.py.
 */
export interface ActorLogEntry {
  element_id: string;
  actor: string;
  kind: "capability" | "human" | string;
  at: string;
}

export interface InstanceHitlLink {
  task_id: string;
  element_id: string;
  status: string;
  hitl_mode: string;
  role: string;
}

export interface InstanceDetail {
  instance: ProcessInstance;
  status: InstanceStatus | string;
  outcome: string | null;
  artifact_names: string[];
  actor_log: ActorLogEntry[];
  hitl_tasks: InstanceHitlLink[];
}

/**
 * GET /instances/{id}/state — flag-guarded (AGENTRT_ENABLE_DEBUG_API), NO
 * response_model. 404 when the flag is off. Keep in sync with instances.py.
 */
export interface InstanceState {
  process_instance_id: string;
  status: InstanceStatus | string;
  outcome: string | null;
  artifacts: Record<string, unknown>;
  actor_log: ActorLogEntry[];
  trace: Record<string, unknown>;
  last_error: string | null;
}
