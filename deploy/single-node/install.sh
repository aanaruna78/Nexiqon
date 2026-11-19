#!/usr/bin/env bash
# Nexiqon single-node install (DV-05) and air-gapped install (DV-06).
#
#   ./install.sh --host ai.example.com --oidc-issuer https://login.example.com/realms/corp
#   ./install.sh ... --gpu                      # self-hosted models on this server's NVIDIA GPUs
#   ./install.sh ... --offline                  # air-gapped: images and model weights from the bundle
#   ./install.sh ... --licence ./customer.licence
#   ./install.sh ... --tls-cert cert.pem --tls-key key.pem   # else a private CA (README)
#   ./install.sh ... --force                    # continue below the recommended size (trials)
#
# Safe to run again: existing passwords, keys, data and settings are kept; it only fills in what
# is missing and (re)starts the services. Everything it writes stays in this directory and in
# Docker volumes.
set -euo pipefail
cd "$(dirname "$0")"
START=$(date +%s)

HOST="" ISSUER="" JWKS="" CLIENT_ID="nexiqon-studio" GPU=0 OFFLINE=0 LICENCE="" CERT="" KEY="" FORCE=0
PROJECT="${NEXIQON_PROJECT:-nexiqon}"
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --oidc-issuer) ISSUER="$2"; shift 2 ;;
    --oidc-jwks-url) JWKS="$2"; shift 2 ;;
    --oidc-client-id) CLIENT_ID="$2"; shift 2 ;;
    --gpu) GPU=1; shift ;;
    --offline) OFFLINE=1; shift ;;
    --licence) LICENCE="$2"; shift 2 ;;
    --tls-cert) CERT="$2"; shift 2 ;;
    --tls-key) KEY="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;   # below the recommended size: warn instead of stopping
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }
rand() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c "${1:-40}"; }
dc() { docker compose -p "$PROJECT" --env-file .env "$@"; }

# ------------------------------------------------------------------ 1. preflight
say "Checking this server"
command -v docker >/dev/null || fail "Docker is not installed (docs: README, Requirements)"
docker info >/dev/null 2>&1 || fail "Docker is not running, or this user may not use it"
CV=$(docker compose version --short 2>/dev/null || echo 0)
printf '%s\n2.24.0\n' "$CV" | sort -V -C 2>/dev/null && fail "Docker Compose $CV is too old: 2.24 or later is needed"
MEM_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
CPUS=$(nproc)
DISK_GB=$(df -Pk . | awk 'NR==2 {print int($4/1024/1024)}')
size() { if [ "$FORCE" = 1 ]; then printf '\033[33m!!\033[0m %s (--force)\n' "$1"; else fail "$1"; fi; }
[ "$MEM_GB" -ge 15 ] || size "$MEM_GB GB of memory: at least 16 GB is needed (README, Sizing)"
[ "$CPUS" -ge 4 ] || size "$CPUS CPUs: at least 4 are needed"
[ "$DISK_GB" -ge 60 ] || size "$DISK_GB GB free here: at least 60 GB is needed (more with --gpu)"
if [ "$GPU" = 1 ]; then
  command -v nvidia-smi >/dev/null || fail "--gpu: nvidia-smi not found (install the NVIDIA driver)"
  docker info 2>/dev/null | grep -qi nvidia || fail "--gpu: the NVIDIA Container Toolkit is not configured for Docker"
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | sed 's/^/    GPU: /'
fi
echo "    $CPUS CPUs, $MEM_GB GB memory, $DISK_GB GB free disk, Compose $CV"

# ------------------------------------------------------------------ 2. images (offline: from the bundle)
if [ "$OFFLINE" = 1 ]; then
  [ -d ../../images ] || fail "--offline: no images/ directory in the bundle"
  say "Loading images from the bundle"
  ( cd ../.. && sha256sum --quiet -c SHA256SUMS ) || fail "the bundle is damaged: checksums do not match"
  for f in ../../images/*.tar; do docker load -q -i "$f"; done
fi

# ------------------------------------------------------------------ 3. .env (passwords are made once)
VERSION_FILE=../../VERSION
if [ ! -f .env ]; then
  [ -n "$HOST" ] || fail "--host is required on the first run (the name users open, e.g. ai.example.com)"
  [ -n "$ISSUER" ] || fail "--oidc-issuer is required on the first run (your identity provider)"
  say "Writing .env (passwords and secrets for this server)"
  umask 077
  cat > .env <<EOF
# Written by install.sh on $(date -u +%F). Keep private: it holds this installation's passwords.
NEXIQON_VERSION=$( [ -f "$VERSION_FILE" ] && cat "$VERSION_FILE" || echo "${NEXIQON_VERSION:-dev}" )
NEXIQON_HOST=$HOST
OIDC_ISSUER=$ISSUER
OIDC_JWKS_URL=${JWKS:-${ISSUER%/}/protocol/openid-connect/certs}
OIDC_CLIENT_ID=$CLIENT_ID
OIDC_CLIENT_SECRET=
NEXIQON_DB_PASSWORD=$(rand)
NEXIQON_APP_DB_PASSWORD=$(rand)
STUDIO_SESSION_SECRET=$(rand 64)
NEXIQON_S3_ACCESS_KEY=nexiqon-$(rand 8)
NEXIQON_S3_SECRET_KEY=$(rand)
NEXIQON_REQUIRE_ADMIN_MFA=true
HF_HUB_OFFLINE=$OFFLINE
# Model provider keys (optional; leave empty on air-gapped servers):
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
# Outgoing email (optional): transcripts and notifications.
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_SENDER=
EOF
  umask 022
fi
set -a; . ./.env; set +a

# ------------------------------------------------------------------ 4. settings
say "Writing settings"
mkdir -p config tls
cat > config/settings.yaml <<EOF
# Written by install.sh from .env; edit .env and run install.sh again.
environment: prod
log_json: true
context_cache_seconds: 30
require_admin_mfa: $NEXIQON_REQUIRE_ADMIN_MFA
opa_url: http://opa:8181
idp_providers:
  - name: customer
    kind: oidc
    issuer: "$OIDC_ISSUER"
    jwks_url: "$OIDC_JWKS_URL"
    audiences: []
events: { enabled: true, nats_url: "nats://nats:4222" }
flags: { provider: flagd, flagd_host: flagd, flagd_port: 8013 }
workflows: { enabled: true, address: "temporal:7233" }
EOF
if [ -n "$LICENCE" ]; then cp "$LICENCE" config/licence.jws; fi
if [ -f config/licence.jws ] || [ -f ../../LICENCE_REQUIRED ]; then
  [ -f ../../licence-public-keys.yaml ] || fail "this bundle has no licence-public-keys.yaml"
  {
    echo "licence:"
    echo "  required: true"
    echo "  file: /app/config/licence.jws"
    sed -n '/^licence:/,$p' ../../licence-public-keys.yaml | sed '1d'
  } >> config/settings.yaml
fi
# Settings files hold no secrets (credentials reach the containers from .env as variables).
BLOBS='blobs: { backend: s3, endpoint: "http://objectstore:8333", bucket: nexiqon, region: us-east-1 }'
if [ -n "$SMTP_HOST" ]; then
  EMAIL="email: { backend: smtp, host: \"$SMTP_HOST\", port: $SMTP_PORT, starttls: true, username: \"$SMTP_USERNAME\", sender: \"$SMTP_SENDER\" }"
else
  EMAIL="email: { backend: memory }   # set SMTP_* in .env to send email"
fi
printf '%s\n%s\n' "$BLOBS" "$EMAIL" > config/control-ops.yaml
printf '%s\nscan: { backend: clamav, clamd_host: clamav, clamd_port: 3310 }\n' "$BLOBS" > config/knowledge.yaml
echo "egress: {}" > config/tool-gateway.yaml
echo "{}" > config/model-gateway.yaml
umask 077   # the object store's credentials: read by its (root) process only
cat > config/s3.json <<EOF
{"identities": [{"name": "nexiqon", "credentials": [{"accessKey": "$NEXIQON_S3_ACCESS_KEY", "secretKey": "$NEXIQON_S3_SECRET_KEY"}], "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}
EOF
umask 022
chmod 755 config
chmod 644 config/*.yaml

if [ -n "$CERT" ]; then cp "$CERT" tls/cert.pem; cp "$KEY" tls/key.pem; chmod 644 tls/*.pem; fi
if [ -f tls/cert.pem ]; then TLS="tls /tls/cert.pem /tls/key.pem"; else TLS="tls internal"; fi
cat > config/Caddyfile <<EOF
{
	admin off
}
https://$NEXIQON_HOST {
	$TLS
	reverse_proxy studio:3000
	header -Server
}
https://$NEXIQON_HOST:8443 {
	$TLS
	reverse_proxy gateway:8080 {
		flush_interval -1
	}
	header -Server
}
EOF

# ------------------------------------------------------------------ 5. model weights (offline)
PROFILES=()
if [ "$GPU" = 1 ]; then PROFILES=(--profile gpu); fi
if [ "$OFFLINE" = 1 ] && [ "$GPU" = 1 ]; then
  [ -d ../../models ] || fail "--offline --gpu: no models/ directory in the bundle"
  say "Copying model weights into the models volume"
  docker volume create "${PROJECT}_models" >/dev/null
  docker run --rm --user 0 --entrypoint cp -v "$(cd ../../models && pwd)":/src:ro \
    -v "${PROJECT}_models":/dst "nexiqon/platform:$NEXIQON_VERSION" -a /src/. /dst/
fi

# ------------------------------------------------------------------ 6. start
say "Starting Nexiqon $NEXIQON_VERSION"
if [ "$OFFLINE" = 1 ]; then dc "${PROFILES[@]}" up -d --pull never; else dc "${PROFILES[@]}" up -d; fi

say "Waiting for the platform to be ready"
for _ in $(seq 1 120); do
  bad=$(dc ps --format '{{.Service}} {{.Health}}' | awk '$2 != "" && $2 != "healthy" {print $1}' | tr '\n' ' ')
  [ -z "$bad" ] && break
  sleep 5
done
[ -z "$bad" ] || fail "not healthy after 10 minutes: $bad (docker compose -p $PROJECT logs <service>)"

ELAPSED=$(( ($(date +%s) - START) / 60 ))
cat <<EOF

  Nexiqon is running ($ELAPSED min).
    Studio:          https://$NEXIQON_HOST
    API and widget:  https://$NEXIQON_HOST:8443
  Sign in with your identity provider ($OIDC_ISSUER), client "$OIDC_CLIENT_ID",
  redirect URI https://$NEXIQON_HOST/auth/callback. The first person to sign in creates the
  organization and becomes its owner.
  Back up: ./backup.sh (README, Operations).

EOF
