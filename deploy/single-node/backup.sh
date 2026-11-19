#!/usr/bin/env bash
# Back up a single-node install (DV-05): the database, uploaded files, signing keys and tool
# credentials, into backups/<UTC time>/. Copy that directory off this server (it holds secrets:
# keep it encrypted). Restore: README, Operations.
#
#   ./backup.sh                 # services keep running; the database dump is consistent
set -euo pipefail
cd "$(dirname "$0")"
PROJECT="${NEXIQON_PROJECT:-nexiqon}"
dc() { docker compose -p "$PROJECT" --env-file .env "$@"; }
OUT="backups/$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$OUT"

echo "==> database"
dc exec -T postgres pg_dump -U nexiqon -d nexiqon -Fc > "$OUT/nexiqon.dump"

# Volumes are read through a throwaway container of the platform image (no extra image needed).
. ./.env
for vol in s3data keys baodata; do
  echo "==> volume $vol"
  docker run --rm --user 0 --entrypoint tar -v "${PROJECT}_${vol}":/v:ro \
    "${NEXIQON_IMAGE:-nexiqon/platform}:$NEXIQON_VERSION" -C /v -czf - . > "$OUT/$vol.tar.gz"
done
cp .env "$OUT/env"
cp -r config "$OUT/config"
( cd "$OUT" && sha256sum ./* > SHA256SUMS 2>/dev/null || true )
echo "Backup written to $OUT ($(du -sh "$OUT" | cut -f1)). Copy it off this server."
