# Database snapshot: hosting and restore

## 1. Large snapshot: do not put in the Git repo

- **GitHub** has strict size limits (e.g. 100 MB per file; repo size recommendations). A full indexer DB dump can be hundreds of MB or more compressed.
- **Recommended:** host the snapshot as a **Release asset** on GitHub (Releases → attach `brc20_indexer_YYYYMMDD.sql.gz`) or on external storage (S3, object storage, etc.) and link the URL in the README or Releases notes.
- **Optional:** use **Git LFS** only if the snapshot is small enough and you accept LFS bandwidth limits; for large files, Release assets or external hosting are simpler.

## 2. Restore: two ways

### A) With override (Postgres on host port 5433 or custom)

From the repo root, with `.env` (and optionally override) loaded:

```bash
# If using override, Postgres is on 127.0.0.1:5433 (or POSTGRES_HOST_PORT from .env)
export PGHOST=127.0.0.1 PGPORT=${POSTGRES_HOST_PORT:-5433}
# Load POSTGRES_PASSWORD from .env
source .env 2>/dev/null || true
./scripts/restore_snapshot.sh path/to/brc20_indexer.sql.gz
# Or from URL:
./scripts/restore_snapshot.sh https://github.com/ORG/REPO/releases/download/v1.0/brc20_indexer.sql.gz
```

### B) Default compose (Postgres not published on host)

Start Postgres only, then restore via the container:

```bash
docker compose up -d postgres
# Wait until healthy, then:
gunzip -c path/to/brc20_indexer.sql.gz | docker compose exec -T postgres psql -U indexer -d brc20_indexer
docker compose up -d
```

### C) Automatic restore on first run (optional)

To support “download snapshot and start in one go”, you can:

1. Add a script that: downloads the snapshot from a fixed URL (e.g. from Releases), runs `restore_snapshot.sh`, then `docker compose up -d`.
2. Or document a one-liner that users run once after cloning, e.g.:

   ```bash
   curl -sLf URL_TO_SNAPSHOT -o snapshot.sql.gz
   docker compose up -d postgres && sleep 5
   gunzip -c snapshot.sql.gz | docker compose exec -T postgres psql -U indexer -d brc20_indexer
   docker compose up -d
   ```

Keep the snapshot URL in the README or in a single `SNAPSHOT_URL` in `.env.example` (commented) so maintainers can update it.
