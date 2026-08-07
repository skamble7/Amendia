/**
 * Per-service base URLs. The app is live-only: every request targets the proxy
 * paths, which the Vite dev proxy (dev) or nginx (built image) forward to the
 * backend services. There is no mock mode.
 */
export type ServiceKey = "stub" | "ingestor" | "runtime" | "registry" | "identity" | "glea";

export const SERVICE_BASE: Record<ServiceKey, string> = {
  stub: import.meta.env.VITE_STUB_BASE ?? "/api/stub",
  ingestor: import.meta.env.VITE_INGESTOR_BASE ?? "/api/ingestor",
  runtime: import.meta.env.VITE_RUNTIME_BASE ?? "/api/runtime",
  registry: import.meta.env.VITE_REGISTRY_BASE ?? "/api/registry",
  identity: import.meta.env.VITE_IDENTITY_BASE ?? "/api/identity",
  // ADR-058 Phase E: the GLEA read-models (audit trail, decision trail, lineage, metrics, trace).
  // Optional at the UI layer — the instance page degrades gracefully when it's unreachable.
  glea: import.meta.env.VITE_GLEA_BASE ?? "/api/glea",
};

/** Human label per service, used in connectivity messaging. */
export const SERVICE_LABEL: Record<ServiceKey, string> = {
  stub: "stub-trigger-generator",
  ingestor: "ingestor",
  runtime: "agent-runtime",
  registry: "process-registry",
  identity: "identity",
  glea: "glea-service",
};

/**
 * Base path for the notification-service SSE stream. Deliberately NOT a `request()`
 * service (no `ServiceKey`): the stream is consumed by a dedicated fetch reader
 * (`notificationsStream.ts`), not the JSON request seam.
 */
export const NOTIFICATIONS_BASE: string =
  import.meta.env.VITE_NOTIFICATIONS_BASE ?? "/api/notifications";
