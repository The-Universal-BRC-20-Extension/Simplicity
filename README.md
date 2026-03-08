# Simplicity: Universal BRC-20 Indexer & OPI Framework

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)

> **Plug-and-play.** Clone, configure, run. No host dependencies.

**Use [SKILL.md](SKILL.md) to interact with this repo.** Whether you are testing, building on the API, or developing new features, the agent uses SKILL.md to guide you in your language and adapt to your goal. For step-by-step reading, the rest of this README is below.

**Simplicity** is an open-source indexer for Universal BRC-20 and related protocols. It provides a modular **Operation Proposal Improvement (OPI)** framework, REST API, and optional Curve/Swap/Wrap support. Deploy with Docker in three commands.

---

## The "Why" & Status

- **Purpose:** Turn a Bitcoin (or compatible) RPC endpoint into a queryable index of BRC-20 and OPI operations. No need to run your own indexer logic from scratch.
- **Status:** **Stable, feature-complete, production-ready.** The codebase is maintained as a legacy/open-source reference. New features may be added by the community via Pull Requests; original maintainers do not guarantee active technical support (see [Governance & Future](#governance--future)).

---

## Technical Stack

| Component        | Version / Notes |
|-----------------|-----------------|
| **Runtime**     | Python 3.11+ |
| **Bitcoin**     | Bitcoin Core–compatible RPC (e.g. Bitcoin Core 24+ with `txindex=1`, or external providers: QuickNode, Alchemy, etc.). Single `BITCOIN_RPC_URL` + auth. |
| **Database**    | PostgreSQL 17 (see `docker-compose`). |
| **Cache**       | Redis 7 (optional but recommended for performance). |
| **API**         | FastAPI; OpenAPI/Swagger at `/docs`, ReDoc at `/redoc`. |

The indexer does **not** bundle or require a specific Ordinals implementation (e.g. `ord`); it uses standard Bitcoin RPC calls (`getblock`, `getblockhash`, etc.) and can work with any RPC-compatible node or API provider.

---

## The 5-Minute Setup

For guided interaction with the repo (testing, API, development), use **[SKILL.md](SKILL.md)**.

**Prerequisites:** Docker and Docker Compose. No Python or PostgreSQL installed on the host.

**Simplest:** run the setup script, then start the stack:
```bash
git clone https://github.com/The-Universal-BRC-20-Extension/simplicity.git
cd simplicity
chmod +x scripts/setup.sh && ./scripts/setup.sh
docker compose up -d   # or: docker compose --profile bitcoind up -d (if you chose "install Bitcoin in Docker")
```
The script asks: (1) Is Bitcoin RPC on this machine? → if yes, uses the host override (127.0.0.1). (2) If no, checks free disk (~750 GB) and can configure **Bitcoin Core in Docker** (profile `bitcoind`). It also sets `.env` and optionally the API port. Then use the manual steps below if you prefer.

1. **Clone**
   ```bash
   git clone https://github.com/The-Universal-BRC-20-Extension/simplicity.git
   cd simplicity
   ```

2. **Configure**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set at least:
   - `POSTGRES_PASSWORD` – used by the Postgres container.
   - `BITCOIN_RPC_URL` – your Bitcoin node or external API URL (e.g. `http://localhost:8332` or `https://your-endpoint.quicknode.com`).
   - `BITCOIN_RPC_USER` / `BITCOIN_RPC_PASSWORD` (or use `BITCOIN_RPC_COOKIE_FILE` for local Bitcoin Core).  
   - **External providers (QuickNode, Alchemy):** set `BITCOIN_RPC_API_KEY` to your token and optionally `BITCOIN_RPC_AUTH_HEADER` (`Bearer`, `x-token`, or `api-key`). See [External RPC providers](#external-rpc-providers) below.

   For Docker, `DATABASE_URL` and `REDIS_URL` are set automatically in `docker-compose`; you can override in `.env` if needed.  
   **If Bitcoin Core runs on this machine:** use the host-network override so the indexer works out of the box: `cp docker-compose.override.yml.example docker-compose.override.yml` (see [Docker ready-to-go when Bitcoin Core runs on the host](#docker-ready-to-go-when-bitcoin-core-runs-on-the-host-recommended)).

3. **Run**
   ```bash
   docker compose up -d
   ```
   This starts:
   - **postgres** – database
   - **redis** – cache
   - **migrate** – runs Alembic migrations once
   - **indexer** – continuous indexing (`python run.py --indexer-only --continuous`)
   - **api** – REST API (port from `API_PORT` in `.env`, default **8080**)

4. **Verify**
   ```bash
   curl http://localhost:8080/health
   # {"status":"ok"}
   curl http://localhost:8080/v1/indexer/brc20/health
   ```
   (Use the port from `API_PORT` in `.env` if you changed it, e.g. 8085.)
   Or run the full validation script (checks .env, waits for API, calls health/status, shows last indexer logs):
   ```bash
   chmod +x scripts/validate_docker.sh
   ./scripts/validate_docker.sh
   # With --start to run docker-compose up -d first: ./scripts/validate_docker.sh --start
   ```

API docs: `http://localhost:8080/docs` (Swagger), `http://localhost:8080/redoc` (ReDoc). Set `API_PORT` in `.env` (e.g. 8085) to use another port.

---

## Quick start for testers / reviewers (pre-publication)

**You are testing this repo and have access to the pre-publish organization.** Use this section to get a running stack with a pre-filled database in a few minutes. **This workflow is temporary:** it only applies during the pre-publication phase while the DB snapshot is hosted in an org-only release. After the project is public, end users will use a **public** snapshot URL in `SNAPSHOT_URL` and will not need to download the file manually.

1. **Clone and configure**
   ```bash
   git clone <this-repo-url>
   cd simplicity
   cp .env.example .env
   ```
   Edit `.env`: set `POSTGRES_PASSWORD`, `BITCOIN_RPC_URL`, `BITCOIN_RPC_USER`, `BITCOIN_RPC_PASSWORD` (or cookie). Set `API_PORT=8085` (or another port) if you want.

2. **Get the DB snapshot**  
   In the org you have access to, open **Releases** and pick the latest snapshot release (e.g. tag `snapshot_20260204_934907`). Download the **asset** (the `.sql.gz` file) from that release. Do not use the "Source code" archives — use the actual asset link (e.g. `brc20_indexer_20260204_block934907.sql.gz`).

3. **Put the snapshot in the repo**
   ```bash
   mkdir -p backups
   mv /path/to/brc20_indexer_YYYYMMDD_blockNNNNNN.sql.gz backups/
   ```
   Replace with the exact filename you downloaded.

4. **Tell Docker to use it**
   In `.env`, add (path is **inside** the container; `backups/` is mounted as `/backups`):
   ```bash
   SNAPSHOT_FILE=/backups/brc20_indexer_20260204_block934907.sql.gz
   ```
   Use the **exact** filename that is in `backups/`.

5. **Start the stack**
   ```bash
   docker compose up -d
   docker compose logs -f restore
   ```
   Wait until you see **"Restore finished successfully."** Then the indexer and API will start. The indexer will resume from the snapshot block (e.g. 934908).

6. **If migrate fails with "Can't locate revision"**  
   The snapshot was built from another branch; align the DB with this repo’s migrations:
   ```bash
   docker compose exec postgres psql -U indexer -d brc20_indexer -c "UPDATE alembic_version SET version_num = '20260202_01';"
   docker compose run --rm migrate python -m alembic -c /app/alembic.ini upgrade head
   docker compose up -d
   ```
   See [docs/SNAPSHOT.md](docs/SNAPSHOT.md) for more.

**Verify:** `curl http://localhost:8085/v1/indexer/brc20/status` (use your `API_PORT`). You should see `last_indexed_brc20_op_block` at or near the snapshot block.

### How Docker connects to Bitcoin and Postgres

- **Bitcoin RPC:** The indexer container reads `BITCOIN_RPC_URL`, `BITCOIN_RPC_USER`, `BITCOIN_RPC_PASSWORD` (and optionally `BITCOIN_RPC_COOKIE_FILE` or `BITCOIN_RPC_API_KEY` for external providers) from your `.env` via `docker-compose`. The URL must be reachable **from inside the container**: use `http://host.docker.internal:8332` if Bitcoin runs on the host (Mac/Windows; on Linux, `extra_hosts` in `docker-compose.yml` enables `host.docker.internal`), or use an external URL (e.g. QuickNode, Alchemy). You can also run **Bitcoin Core in Docker** (~750 GB): set `BITCOIN_RPC_URL=http://bitcoind:8332` and start with `docker compose --profile bitcoind up -d` (see setup script).  
  **If Bitcoin Core runs on the host and you get "Connection refused":** by default RPC binds to `127.0.0.1` only. Allow the Docker network in `bitcoin.conf`, e.g. `rpcbind=0.0.0.0` and `rpcallowip=127.0.0.1` plus `rpcallowip=172.17.0.0/16` (default Docker bridge). Then restart Bitcoin Core.

- **PostgreSQL:** `docker-compose` **overrides** `DATABASE_URL` for the migrate, indexer, and api services so they use hostname `postgres` and port `5432` (the Postgres service). Your `.env` can keep a localhost URL for local runs; inside containers the override ensures the correct connection. Postgres is started first and has a healthcheck; migrate runs after Postgres is healthy, then indexer and api start after migrate completes.

- **Redis:** Same idea: `REDIS_URL` is set to `redis://redis:6379/0` in the compose file for the indexer and api containers.

### Docker ready-to-go when Bitcoin Core runs on the host (recommended)

If the indexer in Docker gets **403 Forbidden** from Bitcoin RPC (common when the node is on the host and only allows `127.0.0.1`), or you want the indexer to behave **exactly like a local run** (pipenv), use the **host-network override** so the indexer uses the host network and connects to `127.0.0.1`:

1. Copy the override file:
   ```bash
   cp docker-compose.override.yml.example docker-compose.override.yml
   ```
2. In `.env`, set `BITCOIN_RPC_URL=http://127.0.0.1:8332` and your `BITCOIN_RPC_USER` / `BITCOIN_RPC_PASSWORD` (or cookie). The override already points the indexer at `127.0.0.1` for Postgres, Redis, and Bitcoin RPC.
3. Run as usual:
   ```bash
   docker compose up -d
   ```

The override publishes Postgres (`5432`) and Redis (`6379`) on the host and runs the **indexer** with `network_mode: host`, so it sees `127.0.0.1` like pipenv. The API and other services stay on the Docker network. This is the recommended way to run Docker when your Bitcoin node is on the same machine.

### External RPC providers

You can use a **Bitcoin Core–compatible JSON-RPC** endpoint from a hosted provider instead of running your own node. Set `BITCOIN_RPC_URL` to the provider’s HTTP(S) endpoint and use **header-based auth** (no Basic user/password):

| Provider   | Auth | In `.env` |
|-----------|------|-----------|
| **QuickNode** | `x-token` header (or token in URL path) | `BITCOIN_RPC_URL=https://your-endpoint.quiknode.pro/`, `BITCOIN_RPC_API_KEY=<token>`, `BITCOIN_RPC_AUTH_HEADER=x-token` |
| **Alchemy**   | API key in header | `BITCOIN_RPC_URL=https://btc-mainnet.g.alchemy.com/v2/...`, `BITCOIN_RPC_API_KEY=<your-api-key>`, keep `BITCOIN_RPC_AUTH_HEADER=Bearer` (default) |

- Leave `BITCOIN_RPC_USER` / `BITCOIN_RPC_PASSWORD` unset or leave as placeholders when using `BITCOIN_RPC_API_KEY`.
- **Maestro:** Their Bitcoin Node RPC is REST-style (per-resource URLs), not a single JSON-RPC POST endpoint, so it is **not compatible** with this indexer unless they offer a standard JSON-RPC endpoint.

---

## Database Snapshot (Avoid Full Re-index)

Indexing from genesis is slow. To get up to speed quickly:

- **Testers / reviewers (pre-publication):** If you have access to the org where the snapshot is hosted, follow **[Quick start for testers / reviewers (pre-publication)](#quick-start-for-testers--reviewers-pre-publication)** above: download the `.sql.gz` from the org’s Releases, put it in `backups/`, set `SNAPSHOT_FILE` in `.env`, then `docker compose up -d`. That flow is **temporary** for this phase; after publication, snapshots will be public and users can use `SNAPSHOT_URL` instead.
- **Automatic (general):** Use one of two options in `.env`. (1) **Local file:** put the `.sql.gz` in `backups/` and set `SNAPSHOT_FILE=/backups/brc20_indexer_YYYYMMDD_blockNNNNNN.sql.gz`. (2) **Public URL:** set `SNAPSHOT_URL` to a **public** snapshot URL. The first time you run `docker compose up -d`, the **restore** service will load the snapshot if the DB is empty. See [docs/SNAPSHOT.md](docs/SNAPSHOT.md).

1. **Obtain a snapshot**  
   A published snapshot is at [simplicity-pre-publish Releases](https://github.com/temp-simplicity/simplicity-pre-publish/releases) (tag `snapshot_20260203_934868`, block 934868). Otherwise check the main repo [Releases](https://github.com/The-Universal-BRC-20-Extension/simplicity/releases) or create your own backup (see below).

2. **Restore**  
   - Start Postgres (e.g. `docker compose up -d postgres`) and wait until it’s healthy.  
   - Restore with the script (if using override so Postgres is on host port):
     ```bash
     ./scripts/restore_snapshot.sh path/to/brc20_indexer.sql.gz
     # or from URL: ./scripts/restore_snapshot.sh https://.../brc20_indexer.sql.gz
     ```
     Or without override (Postgres only in Docker):
     ```bash
     gunzip -c brc20_indexer_YYYYMMDD.sql.gz | docker compose exec -T postgres psql -U indexer -d brc20_indexer
     ```
   - Then start the rest of the stack: `docker compose up -d`.  
   **Large snapshots:** do not commit them to the repo; host on [Releases](https://github.com/The-Universal-BRC-20-Extension/simplicity/releases) or external storage. See [docs/SNAPSHOT.md](docs/SNAPSHOT.md).

3. **Create your own backup**  
   Use the provided script (uses `PG*` or `POSTGRES_*` env vars; run from host or a container with `pg_dump` and network access to Postgres):
   ```bash
   # From host (Docker): ensure .env is loaded and Postgres is reachable
   export PGHOST=localhost PGPORT=5432 PGUSER=indexer PGPASSWORD=your_password PGDATABASE=brc20_indexer
   ./scripts/backup.sh
   ```
   Output: `backups/brc20_indexer_<timestamp>.sql.gz`. See `scripts/backup.sh` for more options.

---

## Clean and re-run

If the API fails with **"port 8080 already in use"**, set `API_PORT=8081` (or another free port) in `.env` so the API binds to that port instead.

To tear down, rebuild, and start again (e.g. after changing `.env` or the override):

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

To also remove volumes (full reset: database and Redis data are deleted):

```bash
docker compose down -v
docker compose build --no-cache
docker compose up -d
```

---

## Minimal Maintenance

- **Disk:** Monitor disk space for Postgres data and logs. Index and log growth depend on chain activity and retention.
- **Bitcoin node:** Keep your node (or external RPC) synced and reachable; update `BITCOIN_RPC_*` if the endpoint or credentials change.
- **Updates:** Pull image/code updates and re-run migrations if needed (`docker compose build`, then `docker compose up -d`; the `migrate` service runs on startup).
- **Logs:** Indexer logs are in the `indexer_logs` volume; use `docker compose logs -f indexer` or `docker compose logs -f api` to inspect.

---

## Key Features

- **High performance:** Sub-20 ms response times for cached queries where Redis is used.
- **Protocol coverage:** Universal BRC-20 (deploy, mint, transfer) and OPI-based extensions (e.g. swap, wrap, curve).
- **Modular OPI framework:** New operations can be added as OPI modules without changing core indexer logic.
- **Dockerized:** Indexer, API, Postgres, and Redis run in containers; no global installs required.
- **Bitcoin node abstraction:** Use a local Bitcoin Core node or an external RPC provider (QuickNode, Alchemy, etc.) via `BITCOIN_RPC_URL` and credentials in `.env`.
- **API:** REST with OpenAPI at `/docs` and `/redoc`; see `docs/api/README.md` and `docs/api/openapi.yaml` for details.

---

## Governance & Future

- **Pull Requests:** Contributions are welcome. Open an issue first for large or breaking changes. Follow the existing code style and add tests where relevant.
- **Support:** The original maintainers provide this project as-is. They do **not** guarantee active technical support, response to issues, or security patches. Use at your own risk.
- **Maintainers:** The project may be looking for new maintainers. See [MAINTAINERS.md](MAINTAINERS.md) for run/release and handover notes.
- **Critical endpoints to monitor** if you operate an instance:
  - `GET /health` – lightweight liveness.
  - `GET /v1/indexer/brc20/health` – indexer/BRC-20 API status.
  - `GET /v1/indexer/brc20/status` – block heights and sync status.
  - `GET /health/concurrency` – duplicate blocks / reorg hints (if implemented).

For full API reference, see `docs/api/README.md` and the OpenAPI spec in `docs/api/openapi.yaml`.

---

## TODO – Future missions

For future developers / next missions (not a current priority) :

- **Reorg handling with Swap** : Implement full reorg handling for Swap operations (position expiration, refund, rollback of swap.init/swap.exe on reorg). Tests `test_reorg_around_expiration` and `test_expiration_volume_huge_parametrized` are currently skipped.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
