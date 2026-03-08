#!/usr/bin/env bash
# Restore a database snapshot into the running Postgres (Docker or local).
# Usage:
#   ./scripts/restore_snapshot.sh path/to/snapshot.sql.gz
#   ./scripts/restore_snapshot.sh https://github.com/.../releases/download/.../brc20_indexer.sql.gz
#
# Requires: Postgres running (e.g. docker compose up -d postgres). Uses POSTGRES_* or PG* from .env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <snapshot.sql.gz or URL>" >&2
  echo "Example: $0 backups/brc20_indexer_20250101_120000.sql.gz" >&2
  echo "Example: $0 https://github.com/org/repo/releases/download/v1.0/brc20_indexer.sql.gz" >&2
  exit 1
fi

SNAPSHOT="$1"

# Load .env for POSTGRES_*
if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  source .env 2>/dev/null || true
  set +a
fi

# Connection: override uses 5433 on host, default compose uses postgres:5432 from host we use 5432 or POSTGRES_HOST_PORT
PGHOST="${PGHOST:-127.0.0.1}"
# With override, host port is 5433 by default (or POSTGRES_HOST_PORT). Without override, use docker compose exec (see docs/SNAPSHOT.md).
PGPORT="${PGPORT:-${POSTGRES_HOST_PORT:-5433}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-indexer}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-brc20_indexer}}"

if [ -z "$PGPASSWORD" ]; then
  echo "Error: PGPASSWORD or POSTGRES_PASSWORD must be set (e.g. in .env)." >&2
  exit 1
fi

export PGPASSWORD

if [[ "$SNAPSHOT" = https?://* ]]; then
  echo "Downloading snapshot from URL..."
  curl -sLf "$SNAPSHOT" | gunzip | psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --set ON_ERROR_STOP=on
else
  if [ ! -f "$SNAPSHOT" ]; then
    echo "Error: file not found: $SNAPSHOT" >&2
    exit 1
  fi
  echo "Restoring from $SNAPSHOT..."
  gunzip -c "$SNAPSHOT" | psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --set ON_ERROR_STOP=on
fi

echo "Restore finished. Start the rest of the stack: docker compose up -d"
