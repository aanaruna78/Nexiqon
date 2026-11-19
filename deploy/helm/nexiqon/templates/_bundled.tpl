{{/* A single-replica Deployment + Service for a bundled dependency (evaluation only). */}}
{{- define "nexiqon.bundled.simple" -}}
{{- $root := index . 0 }}{{ $name := index . 1 }}{{ $image := index . 2 }}{{ $ports := index . 3 }}{{ $args := index . 4 }}{{ $env := index . 5 }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ $name }}
  labels: {{- include "nexiqon.labels" $root | nindent 4 }}
spec:
  replicas: 1
  strategy: { type: Recreate }
  selector:
    matchLabels: {{- include "nexiqon.selector" (dict "root" $root "name" $name) | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "nexiqon.labels" $root | nindent 8 }}
        app.kubernetes.io/name: {{ $name }}
    spec:
      containers:
        - name: {{ $name }}
          image: {{ $image }}
          {{- with $args }}
          args: {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with $env }}
          env: {{- toYaml . | nindent 12 }}
          {{- end }}
          ports:
            {{- range $p := $ports }}
            - { name: {{ $p.name }}, containerPort: {{ $p.port }} }
            {{- end }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $name }}
  labels: {{- include "nexiqon.labels" $root | nindent 4 }}
spec:
  selector: {{- include "nexiqon.selector" (dict "root" $root "name" $name) | nindent 4 }}
  ports:
    {{- range $p := $ports }}
    - { name: {{ $p.name }}, port: {{ $p.port }}, targetPort: {{ $p.name }} }
    {{- end }}
{{- end }}
