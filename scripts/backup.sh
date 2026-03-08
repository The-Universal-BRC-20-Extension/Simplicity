#!/usr/bin/env bash
# Database backup script for Simplicity indexer.
# Produces a compressed pg_dump suitable for snapshots and restores.
#
# Usage:
#   From host (Docker): PGHOST=localhost PGPORT=5432 PGUSER=indexer PGPASSWORD=xxx PGDATABASE=brc20_indexer ./scripts/backup.sh
#   From host (compose env): export $(grep -v '^#' .env | xargs) && PGHOST=localhost ./scripts/backup.sh
#   Inside Docker: docker-compose exec postgres pg_dump -U indexer brc20_indexer | gzip > backup.sql.gz
#
# Output: backups/<db_name>_<YYYYMMDD_HHMMSS>.sql.gz (create backups/ if missing)

set -euo pipefail

# Connection: prefer PG* env vars, then POSTGRES_* from docker-compose
PGHOST="${PGHOST:-${POSTGRES_HOST:-postgres}}"
PGPORT="${PGPORT:-${POSTGRES_PORT:-5432}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-indexer}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-brc20_indexer}}"

if [ -z "$PGPASSWORD" ]; then
  echo "Error: PGPASSWORD or POSTGRES_PASSWORD must be set." >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-backups}"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="${BACKUP_DIR}/${PGDATABASE}_${TIMESTAMP}.sql.gz"

export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
pg_dump --no-owner --no-privileges --format=plain "$PGDATABASE" | gzip -9 > "$OUTPUT_FILE"

echo "Backup written to $OUTPUT_FILE"
ls -la "$OUTPUT_FILE"
