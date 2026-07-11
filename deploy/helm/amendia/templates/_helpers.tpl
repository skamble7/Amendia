{{/* ── Names & labels ─────────────────────────────────────────────────────── */}}
{{- define "amendia.svc" -}}
{{- printf "%s-%s" .root.Release.Name .name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "amendia.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/part-of: amendia
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version }}
{{- end -}}

{{- define "amendia.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/* image: registry/name:tag */}}
{{- define "amendia.image" -}}
{{- $g := .root.Values.global -}}
{{- printf "%s/%s:%s" $g.imageRegistry .image $g.imageTag -}}
{{- end -}}

{{/* ── Cross-service URLs (built from the release name so any release name works) ── */}}
{{- define "amendia.rabbitUrl" -}}
{{- $v := .Values -}}
amqp://$(RABBIT_USER):$(RABBIT_PASSWORD)@{{ $v.rabbit.host }}:{{ $v.rabbit.port }}/
{{- end -}}

{{/* ── Standard security context (container) ─────────────────────────────── */}}
{{- define "amendia.containerSecurityContext" -}}
securityContext:
  runAsNonRoot: {{ .Values.defaults.securityContext.runAsNonRoot }}
  runAsUser: {{ .Values.defaults.securityContext.runAsUser }}
  allowPrivilegeEscalation: {{ .Values.defaults.securityContext.allowPrivilegeEscalation }}
  readOnlyRootFilesystem: {{ .Values.defaults.securityContext.readOnlyRootFilesystem }}
  capabilities:
    drop: {{ .Values.defaults.securityContext.capabilities.drop | toJson }}
{{- end -}}

{{/* ── Vault (Kubernetes auth). Default method = CSI (Secrets Store CSI + Vault provider):
     secrets sync into a per-service K8s Secret and are consumed via secretKeyRef — portable
     across GKE/EKS/AKS/on-prem, no plaintext anywhere (ADR-016 trap 1 / ADR-022 Part B).
     Agent Injector is the documented values-toggle alternative (pod annotations below). */}}

{{/* Secret env for a service (CSI): env entries sourced from the synced K8s Secret. */}}
{{- define "amendia.secretEnv" -}}
{{- $secretName := printf "%s-secrets" (include "amendia.svc" (dict "root" .root "name" .name)) -}}
{{- range .secretEnv }}
- name: {{ . }}
  valueFrom:
    secretKeyRef:
      name: {{ $secretName }}
      key: {{ . }}
{{- end }}
{{- end -}}

{{/* Agent Injector pod annotations (used when vault.method=agent-injector). Renders the KV
     pairs at the service's Vault path into /vault/secrets/amendia.env (file: refs / sourced). */}}
{{- define "amendia.vaultAnnotations" -}}
{{- if and .root.Values.vault.enabled (eq .root.Values.vault.method "agent-injector") }}
vault.hashicorp.com/agent-inject: "true"
vault.hashicorp.com/role: {{ .root.Values.vault.role | quote }}
vault.hashicorp.com/agent-inject-secret-amendia.env: {{ printf "%s/%s" .root.Values.vault.secretBasePath .name | quote }}
{{- end }}
{{- end -}}

{{/* commonEnv: the prefixed auth + infra env block for a backend service.
     args: dict "root" $ "svc" <serviceMap> */}}
{{- define "amendia.commonEnv" -}}
{{- $v := .root.Values -}}
{{- $svc := .svc -}}
{{- $p := $svc.prefix -}}
- name: {{ $p }}_LOG_LEVEL
  value: "INFO"
- name: {{ $p }}_AUTH_ISSUER
  value: {{ $v.auth.issuer | quote }}
- name: {{ $p }}_AUTH_AUDIENCE
  value: {{ $v.auth.audience | quote }}
- name: {{ $p }}_AUTH_JWKS_URI
  value: {{ $v.auth.jwksUri | quote }}
- name: {{ $p }}_AUTH_IDENTITY_BASE_URL
  value: {{ $v.auth.identityBaseUrl | quote }}
{{- if $svc.mongoDb }}
- name: {{ $p }}_MONGO_URI
  value: {{ $v.mongo.uri | quote }}
- name: {{ $p }}_MONGO_DB
  value: {{ $svc.mongoDb | quote }}
{{- end }}
{{- if $svc.rabbit }}
- name: {{ $p }}_RABBITMQ_URL
  value: {{ include "amendia.rabbitUrl" .root | quote }}
{{- end }}
{{- if $svc.registry }}
- name: {{ $p }}_REGISTRY_BASE_URL
  value: {{ $v.registry.url | quote }}
{{- end }}
{{- if $svc.configForge }}
- name: {{ $p }}_CONFIG_FORGE_URL
  value: {{ $v.configForge.url | quote }}
{{- end }}
{{- end -}}

{{/* extraEnv: verbatim map → env list, with __MONGO_URI__ substitution for config-forge */}}
{{- define "amendia.extraEnv" -}}
{{- $v := .root.Values -}}
{{- range $k, $val := .svc.extraEnv }}
- name: {{ $k }}
  value: {{ (eq $val "__MONGO_URI__") | ternary $v.mongo.uri $val | quote }}
{{- end }}
{{- end -}}
