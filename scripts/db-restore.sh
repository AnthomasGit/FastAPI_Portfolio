#!/usr/bin/env bash
# Restore a Storyboard Pro DB dump into the compose Postgres container.
# OVERWRITES the current database. Requires typed confirmation.
# Usage: scripts/db-restore.sh [path/to/file.dump]   (defaults to newest in ./backups/)
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

CONTAINER="${DB_CONTAINER:-local-portfolio-db}"
DB_USER="${DB_USER:-portfolio_user}"
DB_NAME="${DB_NAME:-portfolio_db}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/backups"

FILE="${1:-}"
if [ -z "$FILE" ]; then
  FILE="$(ls -1t "$OUT_DIR/${DB_NAME}_"*.dump 2>/dev/null | head -1 || true)"
fi
if [ -z "$FILE" ] || [ ! -s "$FILE" ]; then
  echo "ERROR: no dump specified and none found in $OUT_DIR" >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "ERROR: container '$CONTAINER' not running." >&2
  exit 1
fi

echo "About to OVERWRITE database '$DB_NAME' in container '$CONTAINER'"
echo "  restore source: $FILE"
read -r -p "Type the database name ('$DB_NAME') to confirm: " reply
if [ "$reply" != "$DB_NAME" ]; then
  echo "Aborted."
  exit 1
fi

docker exec -i "$CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" \
  --clean --if-exists --no-owner < "$FILE"

echo "Restore complete from $FILE"
