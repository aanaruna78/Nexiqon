#!/usr/bin/env bash
# Stop everything started by ./start.sh: Studio and the whole Docker Compose stack (all profiles).
#
#   ./stop.sh           # stop; data (database, files, queues) is kept for next time
#   ./stop.sh --wipe    # stop AND delete all local data volumes (asks first)
set -euo pipefail
cd "$(dirname "$0")"

WIPE=0
case "${1:-}" in
  --wipe) WIPE=1 ;;
  -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
  "") ;;
  *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
esac

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

if [ -f .local/studio.pid ]; then
  pid=$(cat .local/studio.pid)
  if kill -0 "$pid" 2>/dev/null; then
    say "Stopping Studio"
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  fi
  rm -f .local/studio.pid
else
  # Started some other way (make studio in a terminal): stop it by its command line.
  pkill -f "next dev --port 3100" 2>/dev/null && say "Stopping Studio" || true
fi

COMPOSE=(docker compose -f deploy/compose/docker-compose.yml --profile '*')
if [ "$WIPE" = 1 ]; then
  read -r -p "Delete ALL local Nexiqon data (database, uploaded files, queues)? Type 'wipe' to confirm: " answer
  [ "$answer" = "wipe" ] || { echo "Not wiped."; exit 1; }
  say "Stopping the stack and deleting its volumes"
  "${COMPOSE[@]}" down -v
else
  say "Stopping the stack (data kept)"
  "${COMPOSE[@]}" down
fi
say "Stopped."
