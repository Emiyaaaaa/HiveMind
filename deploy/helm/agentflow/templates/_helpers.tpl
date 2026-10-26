{{- define "agentflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "agentflow.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "agentflow.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "agentflow.labels" -}}
helm.sh/chart: {{ include "agentflow.chart" . }}
{{ include "agentflow.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{- define "agentflow.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agentflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "agentflow.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "agentflow.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "agentflow.jdbcUrl" -}}
{{- if .Values.postgres.enabled }}
{{- printf "jdbc:postgresql://%s-postgres:5432/%s" (include "agentflow.fullname" .) .Values.postgres.auth.database }}
{{- else }}
{{- .Values.database.jdbcUrl }}
{{- end }}
{{- end }}

{{- define "agentflow.sqlalchemyUrl" -}}
{{- if .Values.postgres.enabled }}
{{- printf "postgresql+asyncpg://%s:%s@%s-postgres:5432/%s" .Values.postgres.auth.username .Values.postgres.auth.password (include "agentflow.fullname" .) .Values.postgres.auth.database }}
{{- else }}
{{- .Values.database.sqlalchemyUrl }}
{{- end }}
{{- end }}

{{- define "agentflow.redisHost" -}}
{{- if .Values.redis.enabled }}
{{- printf "%s-redis" (include "agentflow.fullname" .) }}
{{- else }}
{{- .Values.redisExternal.host }}
{{- end }}
{{- end }}

{{- define "agentflow.redisPort" -}}
{{- if .Values.redis.enabled }}
{{- "6379" }}
{{- else }}
{{- .Values.redisExternal.port | int }}
{{- end }}
{{- end }}

{{- define "agentflow.redisUrl" -}}
{{- if .Values.redis.enabled }}
{{- printf "redis://%s-redis:6379/0" (include "agentflow.fullname" .) }}
{{- else }}
{{- .Values.redisExternal.url }}
{{- end }}
{{- end }}

{{- define "agentflow.dbUser" -}}
{{- if .Values.postgres.enabled }}
{{- .Values.postgres.auth.username }}
{{- else }}
{{- .Values.database.username }}
{{- end }}
{{- end }}

{{- define "agentflow.dbPassword" -}}
{{- if .Values.postgres.enabled }}
{{- .Values.postgres.auth.password }}
{{- else }}
{{- .Values.database.password }}
{{- end }}
{{- end }}

{{- define "agentflow.migrateInitContainer" -}}
- name: migrate
  image: "{{ .Values.worker.image.repository }}:{{ .Values.worker.image.tag }}"
  imagePullPolicy: {{ .Values.worker.image.pullPolicy }}
  command:
    - /bin/sh
    - -c
    - |
      i=0
      while [ "$i" -lt 30 ]; do
        uv run alembic upgrade head && exit 0
        i=$((i + 1))
        sleep 2
      done
      exit 1
  env:
    - name: AGENTFLOW_DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: {{ include "agentflow.secretName" . }}
          key: sqlalchemy-url
{{- end }}
