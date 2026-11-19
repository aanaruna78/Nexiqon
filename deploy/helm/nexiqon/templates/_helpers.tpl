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
{{- if and $g.enabled (has $svc $g.services) -}}
{{- $host = ternary $svc $name (eq $root.Values.topology.mode "split") -}}
{{- end -}}
{{- end -}}
{{- $host -}}
{{- end -}}

{{/*
An Envoy cluster for a remote HTTPS endpoint (the control plane link, a region cell): TLS with
SNI and CA validation, and this side's client certificate when the files are mounted (mTLS).
args: (list name host port secretDir clientCert)
*/}}
{{- define "nexiqon.tlsCluster" -}}
{{- $name := index . 0 -}}{{- $host := index . 1 -}}{{- $port := index . 2 -}}{{- $dir := index . 3 -}}{{- $client := index . 4 -}}
- name: {{ $name }}
  type: LOGICAL_DNS
  connect_timeout: 5s
  dns_lookup_family: V4_ONLY
  load_assignment:
    cluster_name: {{ $name }}
    endpoints: [{ lb_endpoints: [{ endpoint: { address: { socket_address: { address: {{ $host }}, port_value: {{ $port }} } } } }] }]
  transport_socket:
    name: envoy.transport_sockets.tls
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext
      sni: {{ $host }}
      common_tls_context:
        validation_context:
          trusted_ca: { filename: {{ $dir }}/ca.crt }
          match_typed_subject_alt_names: [{ san_type: DNS, matcher: { exact: {{ $host }} } }]
        {{- if $client }}
        tls_certificates:
          - certificate_chain: { filename: {{ $dir }}/tls.crt }
            private_key: { filename: {{ $dir }}/tls.key }
        {{- end }}
{{- end -}}

{{/* Services this release does not run, reached through the control-plane link (hybrid data plane). */}}
{{- define "nexiqon.remoteEnv" -}}
{{- if .Values.controlPlane.host -}}
{{- $all := list "identity" "authz" "config" "audit" "evaluation" "metering" "governance" "notification" "ingestion" "retrieval" "agent-runtime" "conversation" "channel" "tool-gateway" "model-gateway" -}}
{{- range $svc := $all -}}
{{- if not (include "nexiqon.hostFor" (list $ $svc)) }}
- name: NEXIQON_SERVICE_URL_{{ $svc | upper | replace "-" "_" }}
  {{- if and (eq $svc "config") (include "nexiqon.hostFor" (list $ "config-mirror")) }}
  value: {{ printf "http://%s:%v/config-mirror" (include "nexiqon.hostFor" (list $ "config-mirror")) $.Values.topology.port | quote }}
  {{- else }}
  value: {{ printf "http://control-link:8081/%s" $svc | quote }}
  {{- end }}
{{- end }}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The groups file the image's runner and service URLs use (mirrors deploy/groups.yaml). */}}
{{- define "nexiqon.groupsFile" -}}
mode: {{ .Values.topology.mode }}
port: {{ .Values.topology.port }}
groups:
{{- range $name, $g := .Values.groups }}
{{- if $g.enabled }}
  {{ $name }}:
    plane: {{ $g.plane }}
    services: {{ toJson $g.services }}
{{- end }}
{{- end }}
{{- end -}}
