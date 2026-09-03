{{- define "agentflow.secretName" -}}
{{- if .Values.database.existingSecret }}
{{- .Values.database.existingSecret }}
{{- else }}
{{- include "agentflow.fullname" . }}
{{- end }}
{{- end }}
