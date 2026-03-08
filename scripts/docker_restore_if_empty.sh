#!/usr/bin/env sh
# Run inside the "restore" Docker service. Waits for Postgres, then if the DB
# is empty, restores from either:
#   - SNAPSHOT_FILE: path inside container (e.g. /backups/brc20_indexer_YYYYMMDD_blockNNNNNN.sql.gz)
#   - SNAPSHOT_URL: public URL (e.g. GitHub Release asset); downloaded with curl, no auth.
# Use one or the other; if both set, SNAPSHOT_FILE takes precedence when the file exists.

set -e
set -o pipefail

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-indexer}"
PGPASSWORD="${PGPASSWORD:?PGPASSWORD or POSTGRES_PASSWORD required}"
PGDATABASE="${PGDATABASE:-brc20_indexer}"
SNAPSHOT_FILE="${SNAPSHOT_FILE:-}"
SNAPSHOT_URL="${SNAPSHOT_URL:-}"

export PGPASSWORD

echo "Waiting for Postgres at $PGHOST:$PGPORT..."
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" 2>/dev/null; do
  sleep 2
done
echo "Postgres is ready."

# Check if DB already has content (alembic_version present from a previous restore or migrate)
if psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A -c "SELECT 1 FROM alembic_version LIMIT 1" 2>/dev/null | grep -q 1; then
  echo "Database already has data (alembic_version present). Skipping restore."
  exit 0
fi

# Prefer local file if set and present
if [ -n "$SNAPSHOT_FILE" ] && [ -f "$SNAPSHOT_FILE" ]; then
  echo "Restoring from local file: $SNAPSHOT_FILE"
  if ! gunzip -c "$SNAPSHOT_FILE" | psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --set ON_ERROR_STOP=on; then
    echo "Restore failed: gunzip or psql error." >&2
    exit 1
  fi
  echo "Restore finished successfully."
  exit 0
fi

if [ -n "$SNAPSHOT_FILE" ] && [ ! -f "$SNAPSHOT_FILE" ]; then
  echo "SNAPSHOT_FILE is set but file not found: $SNAPSHOT_FILE. Skipping restore." >&2
  exit 0
fi

# Otherwise try public URL
if [ -z "$SNAPSHOT_URL" ]; then
  echo "Neither SNAPSHOT_FILE nor SNAPSHOT_URL set. Skipping restore."
  exit 0
fi

echo "Restoring from SNAPSHOT_URL (public download)..."
TMPF="/tmp/snapshot.$$.sql.gz"
if ! curl -sLf -H "Accept: application/octet-stream" -H "User-Agent: Mozilla/5.0 (compatible; SimplicityRestore/1.0)" -o "$TMPF" "$SNAPSHOT_URL"; then
  echo "Restore failed: could not download SNAPSHOT_URL (public URL only; check URL and network)." >&2
  rm -f "$TMPF"
  exit 1
fi
if [ ! -s "$TMPF" ]; then
  echo "Restore failed: downloaded file is empty." >&2
  rm -f "$TMPF"
  exit 1
fi
# Check gzip magic (1f 8b)
if ! (head -c 2 "$TMPF" | od -An -tx1 2>/dev/null | grep -q '1f 8b'); then
  echo "Restore failed: download is not gzip (URL may return HTML/error page)." >&2
  rm -f "$TMPF"
  exit 1
fi
if ! gunzip -c "$TMPF" | psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --set ON_ERROR_STOP=on; then
  echo "Restore failed: gunzip or psql error." >&2
  rm -f "$TMPF"
  exit 1
fi
rm -f "$TMPF"
echo "Restore finished successfully."
exit 0
