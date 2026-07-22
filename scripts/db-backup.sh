#!/usr/bin/env bash
# Back up the Storyboard Pro Postgres DB from the compose container to ./backups/
# on the host. Safe to run anytime; does not stop the stack.
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"   # cron has a minimal PATH

CONTAINER="${DB_CONTAINER:-local-portfolio-db}"
DB_USER="${DB_USER:-portfolio_user}"
DB_NAME="${DB_NAME:-portfolio_db}"
KEEP="${KEEP:-30}"                      # how many dumps to retain

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/backups"
mkdir -p "$OUT_DIR"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "$(date -u +%FT%TZ) ERROR: container '$CONTAINER' not running; skipping backup." >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%d_%H%M%SZ)"
OUT="$OUT_DIR/${DB_NAME}_${STAMP}.dump"

docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$OUT"

if [ ! -s "$OUT" ]; then                # a broken/empty dump must not masquerade as good
  echo "$(date -u +%FT%TZ) ERROR: dump empty; removing $OUT" >&2
  rm -f "$OUT"
  exit 1
fi

echo "$(date -u +%FT%TZ) OK: $(du -h "$OUT" | cut -f1)  $OUT"

# Prune: keep only the newest $KEEP dumps
ls -1t "$OUT_DIR/${DB_NAME}_"*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
