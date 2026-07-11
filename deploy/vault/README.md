# Amendia — Vault secrets (Kubernetes auth)

Portable across GKE / EKS / AKS / on-prem: pods authenticate to Vault with their **Kubernetes
ServiceAccount** (no per-cloud workload-identity dependency for secrets). This realizes ADR-016's
`literal: → vault:` migration — the ConfigForge `ModelProfile` refs stay `env:`/`file:`, but the
**values** those resolve to are Vault-sourced. **No plaintext secret ever lives in Git, values, or a
bare K8s Secret.**

Two delivery methods (chart `vault.method`), **CSI is the default**:
- **`csi`** (default): the Secrets Store CSI driver + Vault provider sync each service's Vault path into
  a per-service K8s Secret, consumed via `secretKeyRef` (the chart renders a `SecretProviderClass` per
  service). Cleanest env mapping.
- **`agent-injector`** (alternative): the Vault Agent Injector renders secrets into `/vault/secrets/`
  (pod annotations); the app reads them as `file:` ConfigForge refs / a sourced env file.

## 1. Enable Kubernetes auth + a role

```bash
vault auth enable kubernetes
vault write auth/kubernetes/config \
  kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443"

# One role bound to every Amendia ServiceAccount, scoped by the policy below.
vault write auth/kubernetes/role/amendia \
  bound_service_account_names="amendia-stub-exception-generator,amendia-ingestor,amendia-agent-runtime,amendia-process-registry,amendia-identity,amendia-notification-service,amendia-config-forge,amendia-capability-worker" \
  bound_service_account_namespaces="amendia" \
  policy="amendia" \
  ttl="1h"
```

## 2. Policy — least privilege per path

Each service reads only `secret/data/amendia/<service>` (see `policy.hcl`). Populate the KV-v2 paths
with the exact env-var keys the chart references (`values.yaml` → `services.<svc>.secretEnv`):

```bash
vault kv put secret/amendia/agent-runtime \
  AGENTRT_AUTH_INTERNAL_TOKEN=... RABBIT_USER=... RABBIT_PASSWORD=... \
  AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... NVIDIA_NIM_API_KEY=... OPENSHELL_INFERENCE_TOKEN=...

vault kv put secret/amendia/capability-worker \
  RABBIT_USER=... RABBIT_PASSWORD=... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
  NVIDIA_NIM_API_KEY=... OPENSHELL_INFERENCE_TOKEN=...

vault kv put secret/amendia/identity  IDENTITY_INTERNAL_TOKEN=...
# ...one path per service (see values.yaml secretEnv lists).
```

`# per-deployment`: your Vault address, namespace, KV mount name, and topology (HA, auto-unseal, PKI)
are customer-specific — adjust `vault.address` / `vault.secretBasePath` accordingly.
