# Amendia Vault policy (KV-v2 at mount "secret"). Least privilege: read-only, per-service paths.
# Bound to the "amendia" Kubernetes-auth role (see README). No write/list of other services' paths.

path "secret/data/amendia/stub-exception-generator" { capabilities = ["read"] }
path "secret/data/amendia/ingestor"                 { capabilities = ["read"] }
path "secret/data/amendia/agent-runtime"            { capabilities = ["read"] }
path "secret/data/amendia/process-registry"         { capabilities = ["read"] }
path "secret/data/amendia/identity"                 { capabilities = ["read"] }
path "secret/data/amendia/notification-service"     { capabilities = ["read"] }
path "secret/data/amendia/config-forge"             { capabilities = ["read"] }
path "secret/data/amendia/capability-worker"        { capabilities = ["read"] }

# NIM licensing (NGC_API_KEY) when inference.mode = nim-selfhosted.
path "secret/data/amendia/nim"                      { capabilities = ["read"] }

# NOTE: for true least-privilege, split into one policy per ServiceAccount and bind each
# separately in the Kubernetes-auth role (a service then cannot read another's path). The single
# policy above is the simple starting point; # per-deployment: tighten to per-SA policies.
