{{/*
Common labels for all resources.
*/}}
{{- define "staemme.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Selector labels (subset of common labels used in matchLabels).
*/}}
{{- define "staemme.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Full name for a profile-specific resource.
Usage: include "staemme.profileName" (dict "Release" .Release "profile" $profile)
*/}}
{{- define "staemme.profileName" -}}
{{ .Release.Name }}-{{ .profile.name }}
{{- end }}
