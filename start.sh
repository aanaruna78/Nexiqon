#!/usr/bin/env bash
# Start everything for local manual testing: the platform stack (Docker Compose) and Studio.
#
#   ./start.sh                       # platform + apps + Studio
#   ./start.sh --with observability  # also Grafana (traces, metrics); comma-separate: observability,scan
#   ./start.sh --no-studio           # stack only
#   ./start.sh --smoke               # also run the gateway smoke test when ready
#
# Stop with ./stop.sh. Studio's log: .local/studio.log
set -euo pipefail
cd "$(dirname "$0")"

EXTRA="" STUDIO=1 SMOKE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --with) EXTRA="$2"; shift 2 ;;
    --no-studio) STUDIO=0; shift ;;
    --smoke) SMOKE=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }
up() { python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=3)" "$1" >/dev/null 2>&1; }

for tool in docker uv node python3; do command -v "$tool" >/dev/null || fail "$tool is not installed"; done
docker info >/dev/null 2>&1 || fail "Docker is not running"

PROFILES="platform,apps${EXTRA:+,$EXTRA}"
COMPOSE=(docker compose -f deploy/compose/docker-compose.yml)
mkdir -p .local

if [ ! -d .venv ] || [ ! -d frontend/node_modules ]; then
  say "First run: installing dependencies (make setup)"
  make setup
fi

say "Starting the stack ($PROFILES); the first run builds the platform image"
make dev-up PROFILES="$PROFILES"

say "Waiting for every service to be healthy"
for _ in $(seq 1 90); do
  waiting=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}}' | awk '$2 != "" && $2 != "healthy" {print $1}' | tr '\n' ' ')
  [ -z "$waiting" ] && break
  sleep 4
done
[ -z "$waiting" ] || fail "still not healthy after 6 minutes: $waiting (docker compose -f deploy/compose/docker-compose.yml logs <service>)"
up http://localhost:8000/gateway/healthz || fail "the gateway (localhost:8000) does not answer"

if [ "$STUDIO" = 1 ]; then
  if up http://localhost:3100/api/health; then
    say "Studio is already running on :3100"
  else
    say "Starting Studio (log: .local/studio.log)"
    setsid nohup make studio > .local/studio.log 2>&1 &
    echo $! > .local/studio.pid
    for _ in $(seq 1 90); do up http://localhost:3100/api/health && break; sleep 2; done
    up http://localhost:3100/api/health || fail "Studio did not start; see .local/studio.log"
  fi
fi

if [ "$SMOKE" = 1 ]; then
  say "Gateway smoke test"
  uv run python tools/dev/smoke_gateway.py
fi

cat <<EOF

  Nexiqon is running locally.

  Studio            http://localhost:3100        sign in: dev / dev-password
  API gateway       http://localhost:8000
  Keycloak (IdP)    http://localhost:8080        admin / admin_dev
  Mailpit (email)   http://localhost:8025        transcripts and notifications land here
  Temporal UI       http://localhost:8233        workflows (evaluations, deletion, retention)
  OpenBao           http://localhost:8200        token: nexiqon-dev-root
  Demo APIs         http://localhost:9000        for testing tools (Actions)
EOF
case ",$EXTRA," in *,observability,*) echo "  Grafana           http://localhost:3000        admin / admin";; esac
cat <<EOF

  Widget test page: frontend/apps/widget/README.md (embed on any local page)
  Stop everything:  ./stop.sh          (./stop.sh --wipe also deletes all local data)

EOF
