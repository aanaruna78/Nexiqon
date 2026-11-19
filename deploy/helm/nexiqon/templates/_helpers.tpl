{{/* Common labels. */}}
{{- define "nexiqon.labels" -}}
app.kubernetes.io/part-of: nexiqon
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "nexiqon.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/name: {{ .name }}
{{- end -}}

{{- define "nexiqon.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end -}}

{{/*
Workloads to run: one per enabled group (grouped), or one per service of the enabled groups
(split). Each carries its group's settings, keys and environment. Returns YAML: name -> spec.
*/}}
{{- define "nexiqon.workloads" -}}
{{- $out := dict -}}
{{- range $name, $g := .Values.groups -}}
{{- if $g.enabled -}}
{{- if eq $.Values.topology.mode "split" -}}
{{- range $svc := $g.services -}}
{{- $_ := set $out $svc (dict "group" $name "services" (list $svc) "spec" $g) -}}
{{- end -}}
{{- else -}}
{{- $_ := set $out $name (dict "group" $name "services" $g.services "spec" $g) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- toYaml $out -}}
{{- end -}}

{{/* Service name -> host serving it (group name when grouped, service name when split). */}}
{{- define "nexiqon.hostFor" -}}
{{- $root := index . 0 -}}{{- $svc := index . 1 -}}
{{- $host := "" -}}
{{- range $name, $g := $root.Values.groups -}}
{{- if has $svc $g.services -}}
{{- $host = ternary $svc $name (eq $root.Values.topology.mode "split") -}}
{{- end -}}
{{- end -}}
{{- $host -}}
{{- end -}}

{{/* The groups file the image's runner and service URLs use (mirrors deploy/groups.yaml). */}}
{{- define "nexiqon.groupsFile" -}}
mode: {{ .Values.topology.mode }}
port: {{ .Values.topology.port }}
groups:
{{- range $name, $g := .Values.groups }}
  {{ $name }}:
    plane: {{ $g.plane }}
    services: {{ toJson $g.services }}
{{- end }}
{{- end -}}
