/**
 * Per-service base URLs. The app is live-only: every request targets the proxy
 * paths, which the Vite dev proxy (dev) or nginx (built image) forward to the
 * backend services. There is no mock mode.
 */
export type ServiceKey = "stub" | "ingestor" | "runtime" | "registry" | "identity";

export const SERVICE_BASE: Record<ServiceKey, string> = {
  stub: import.meta.env.VITE_STUB_BASE ?? "/api/stub",
  ingestor: import.meta.env.VITE_INGESTOR_BASE ?? "/api/ingestor",
  runtime: import.meta.env.VITE_RUNTIME_BASE ?? "/api/runtime",
  registry: import.meta.env.VITE_REGISTRY_BASE ?? "/api/registry",
  identity: import.meta.env.VITE_IDENTITY_BASE ?? "/api/identity",
};

/** Human label per service, used in connectivity messaging. */
export const SERVICE_LABEL: Record<ServiceKey, string> = {
  stub: "stub-exception-generator",
  ingestor: "ingestor",
  runtime: "agent-runtime",
  registry: "process-registry",
  identity: "identity",
};
