# Creating the current DB snapshot (for Docker bootstrap)

Use this to capture the **current** indexer database so others can start Docker with this state (see [Bootstrap with snapshot](#bootstrap-with-snapshot) and [docs/SNAPSHOT.md](../SNAPSHOT.md)).

## 1. Get the current block number (for the filename)

**Option A – from the API (if the indexer/API is running):**
```bash
curl -s http://localhost:8080/v1/indexer/brc20/status | jq -r '.last_indexed_brc20_op_block // .last_indexed_block_main_chain // "unknown"'
```

**Option B – from the database:**
```bash
# With .env loaded (POSTGRES_* or PG*)
source .env 2>/dev/null || true
export PGHOST="${PGHOST:-127.0.0.1}" PGPORT="${PGPORT:-5433}" PGUSER="${PGUSER:-indexer}" PGPASSWORD="${PGPASSWORD:-$POSTGRES_PASSWORD}" PGDATABASE="${PGDATABASE:-brc20_indexer}"
psql -t -c "SELECT COALESCE((SELECT MAX(block_height) FROM brc20_ops), (SELECT version_num FROM alembic_version LIMIT 1)::bigint, 0)"
```

Note the number (e.g. `875008`) for the filename below.

## 2. Naming and location

- **Name:** `brc20_indexer_YYYYMMDD_blockNNNNNN.sql.gz`  
  Example: `brc20_indexer_20250202_block875008.sql.gz`  
  (Date = day you create the dump; block = last indexed BRC-20 op block from step 1.)
- **Where to create it:** `backups/` at the repo root (ignored by Git).  
  For uploading to GitHub Releases later, you can move/copy the file anywhere.

## 3. Run the dump

**Database name is `brc20_indexer`** (not `brc20`).

**If Postgres is on the host (e.g. override with port 5433):**
```bash
source .env 2>/dev/null || true
BLOCK=$(curl -s http://localhost:8080/v1/indexer/brc20/status 2>/dev/null | jq -r '.last_indexed_brc20_op_block // "unknown"')
DATE=$(date +%Y%m%d)
mkdir -p backups
pg_dump -h "${PGHOST:-127.0.0.1}" -p "${PGPORT:-5433}" -U "${POSTGRES_USER:-indexer}" --no-owner --no-privileges --format=plain brc20_indexer | gzip -9 > "backups/brc20_indexer_${DATE}_block${BLOCK}.sql.gz"
# You will be prompted for the Postgres password, or set PGPASSWORD
echo "Created backups/brc20_indexer_${DATE}_block${BLOCK}.sql.gz"
```

**Or use the existing backup script (timestamp instead of block in name):**
```bash
export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=indexer PGPASSWORD=your_password PGDATABASE=brc20_indexer
./scripts/backup.sh
# Then rename to include block number if you want: mv backups/brc20_indexer_*.sql.gz backups/brc20_indexer_YYYYMMDD_blockNNNNNN.sql.gz
```

**If Postgres runs only in Docker (no host port):**
```bash
docker compose exec -T postgres pg_dump -U indexer --no-owner --no-privileges --format=plain brc20_indexer | gzip -9 > backups/brc20_indexer_$(date +%Y%m%d)_block$(curl -s http://localhost:8080/v1/indexer/brc20/status | jq -r '.last_indexed_brc20_op_block').sql.gz
```

## 4. Next: use the snapshot for auto-restore

See [docs/SNAPSHOT.md](../SNAPSHOT.md) for the two supported options:

- **Local file:** leave the `.sql.gz` in `backups/` and set `SNAPSHOT_FILE=/backups/brc20_indexer_YYYYMMDD_blockNNNNNN.sql.gz` in `.env`. Docker will restore from it on first run when the DB is empty.
- **Public URL:** upload the file to a **public** GitHub Release (attach as asset), or to S3 / any public URL. Set `SNAPSHOT_URL` in `.env` to that URL. Docker will download and restore on first run (no authentication; public URLs only).
