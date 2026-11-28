{{- define "invoiceguard.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/* Name of one component's objects. Call with (dict "ctx" $ "component" "api"). */}}
{{- define "invoiceguard.name" -}}
{{- printf "%s-%s" (include "invoiceguard.fullname" .ctx) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "invoiceguard.selectorLabels" -}}
app.kubernetes.io/name: invoiceguard
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "invoiceguard.labels" -}}
{{ include "invoiceguard.selectorLabels" . }}
app.kubernetes.io/part-of: invoiceguard
app.kubernetes.io/version: {{ .ctx.Values.image.tag | trunc 63 | quote }}
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .ctx.Chart.Name .ctx.Chart.Version }}
{{- end -}}

{{/* Lets the pod through the invoiceguard-postgres NetworkPolicy. */}}
{{- define "invoiceguard.databaseClientLabel" -}}
invoiceguard.io/database-client: "true"
{{- end -}}

{{/* Image of one component, tagged with the commit SHA. Call with (dict "ctx" $ "image" "api"). */}}
{{- define "invoiceguard.image" -}}
{{- $tag := required "image.tag is required: the full commit SHA of the images" .ctx.Values.image.tag -}}
{{- printf "%s/invoiceguard-%s:%s" .ctx.Values.image.registry .image $tag -}}
{{- end -}}

{{/* Pod settings shared by every pod. Call with (dict "ctx" $ "uid" 999). */}}
{{- define "invoiceguard.podSpecCommon" -}}
automountServiceAccountToken: false
# No *_SERVICE_HOST / *_PORT variables: a Service called invoiceguard-api would otherwise set
# INVOICEGUARD_API_PORT and the like, which the INVOICEGUARD_ settings would read.
enableServiceLinks: false
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .uid }}
  runAsGroup: {{ .uid }}
  fsGroup: {{ .uid }}
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "invoiceguard.containerSecurityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]
{{- end -}}

{{- define "invoiceguard.validatorUrl" -}}
{{- printf "http://%s:8080/" (include "invoiceguard.name" (dict "ctx" . "component" "validator")) -}}
{{- end -}}

{{/* The XRechnung visualization: the validator pod's second port (ADR-029). */}}
{{- define "invoiceguard.visualizationUrl" -}}
{{- printf "http://%s:8082/" (include "invoiceguard.name" (dict "ctx" . "component" "validator")) -}}
{{- end -}}

{{/* The owner's database URL, for the migration hook and the demo reset only (ADR-022). */}}
{{- define "invoiceguard.ownerDatabaseEnv" -}}
- name: DATABASE_OWNER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.postgres }}
      key: owner-password
- name: INVOICEGUARD_DATABASE_URL
  value: "postgresql+psycopg://{{ .Values.database.owner }}:$(DATABASE_OWNER_PASSWORD)@{{ .Values.database.host }}:{{ .Values.database.port }}/{{ .Values.database.name }}"
{{- end -}}

{{- define "invoiceguard.commonApiEnv" -}}
- name: INVOICEGUARD_ENV
  value: {{ .Values.env | quote }}
- name: INVOICEGUARD_LOG_LEVEL
  value: {{ .Values.logLevel | quote }}
- name: INVOICEGUARD_DEMO_MODE
  value: {{ .Values.demoMode | quote }}
- name: INVOICEGUARD_VALIDATOR_URL
  value: {{ include "invoiceguard.validatorUrl" . | quote }}
- name: INVOICEGUARD_VISUALIZATION_URL
  value: {{ include "invoiceguard.visualizationUrl" . | quote }}
{{- with .Values.embeddingModel }}
- name: INVOICEGUARD_EMBEDDING_MODEL
  value: {{ . | quote }}
{{- end }}
{{- end -}}

{{/* Waits until PostgreSQL accepts connections (the Job may start while it restarts). */}}
{{- define "invoiceguard.waitForDatabase" -}}
- name: wait-for-database
  image: {{ include "invoiceguard.image" (dict "ctx" . "image" "api") }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  command:
    - python
    - -c
    - |
      import socket, sys, time
      for _ in range(150):
          try:
              socket.create_connection(({{ .Values.database.host | quote }}, {{ .Values.database.port }}), timeout=2).close()
              sys.exit(0)
          except OSError:
              time.sleep(2)
      sys.exit("database not reachable")
  resources:
    requests:
      cpu: 10m
      memory: 32Mi
    limits:
      memory: 64Mi
  {{- include "invoiceguard.containerSecurityContext" . | nindent 2 }}
{{- end -}}
