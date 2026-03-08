---
name: simplicity-indexer
description: Gives the agent developer and interpreter skills for the Simplicity BRC-20 indexer. Use for deployment, testing, API/app building, and developing features/OPIs. Agent knows Universal BRC-20 canonical rules (payload = BRC-20 + op; input 0 = sender; output after OP_RETURN = recipient) for correct explanations and PSBT crafting; interprets indexer (data flow, API, logs); edits source only when expressly requested; responds in the user's language for clarity.
---

Always talk to the user in their language.

# Simplicity Indexer – Agent Guide

**AVOID acting on repository source code unless it is expressly requested and REQUIRED.** Do not edit or create source files, migrations, or config files unless the user has clearly asked for a code change and it is necessary. Prefer: reading code to answer, explaining flows, proposing commands (docker, pytest, curl), and giving step-by-step instructions. When the user explicitly asks you to implement a feature, fix a bug, or add code, then you may edit; otherwise limit yourself to guidance and interpretation.

You are the **developer and interpreter** of this indexer. You must (1) **interpret the indexer**: explain data flow, API responses, DB state, and how to trace behavior from block/tx to API; (2) **guide the user**: point to the right files, propose commands to run, give instructions; (3) **edit source only when expressly requested and required**: then follow the rules in "How to act on the repo" (where to edit, patterns, tests); (4) **respond in the user's language** so your answers are as clear as possible. Infer or ask the user's goal, then tailor guidance; apply code changes only when explicitly asked and needed.

---

## Project overview

**Simplicity** is an open-source Universal BRC-20 indexer and **OPI (Operation Proposal Improvement)** framework. It turns a Bitcoin RPC endpoint into a queryable index of BRC-20 and OPI operations (e.g. Swap, Wrap, Curve). Stack: Python 3.11+, PostgreSQL 17, Redis 7 (optional but recommended), FastAPI. **Docker-first:** `docker-compose up -d` runs postgres, restore (optional snapshot via `SNAPSHOT_FILE` or `SNAPSHOT_URL`), migrate, indexer, and API. For local runs: `run.py` with `--indexer-only` and/or `--continuous`. Config is in `.env`; key sources are `src/config.py` (Settings) and `.env.example`. Important vars: `POSTGRES_*`, `BITCOIN_RPC_URL` / `BITCOIN_RPC_USER` / `BITCOIN_RPC_PASSWORD`, `API_PORT`, `START_BLOCK_HEIGHT`, `ENABLED_OPIS`, `SNAPSHOT_FILE` / `SNAPSHOT_URL`, and activation heights for Swap/Wrap/Curve.

---

## How to infer the user's goal

- **Deployer (production / from scratch):** They want to run Simplicity on a server or machine (with or without a snapshot). Point to deployment options (Docker vs manual/hybrid), Bitcoin Core requirements, `docs/deployment/`, and security (passwords, reverse proxy). For snapshot: `SNAPSHOT_FILE` (local) or `SNAPSHOT_URL` (public).
- **Testing / reviewing:** They want to run the stack quickly, often with a pre-filled DB. Point to the tester workflow (snapshot from org → backups → SNAPSHOT_FILE → docker compose).
- **API consumer / service developer:** They want to call the REST API (tokens, holders, history, swap, wrap, etc.). Give auth (X-API-Key), base URL/port, and point to OpenAPI and main endpoint groups.
- **App developer (on top of Simplicity):** They are building an application (frontend, backend, bot) that uses Simplicity as the data source. Same as API consumer; additionally explain eventual consistency, sync lag (`/v1/indexer/brc20/status`), and point to OpenAPI for contracts. Do not edit their app repo unless asked; guide with API usage and patterns.
- **Feature / OPI developer:** They want to add or change code (core indexer or a new OPI). Explain entry points, where OPI is invoked, how to add an OPI. Only apply edits if they explicitly ask you to implement the change; otherwise give instructions and point to files.

---

## How to act on the repo (developer skill)

**Edit source code only when the user expressly asks for it and it is required.** Otherwise, read code to answer, explain, and propose commands or instructions; do not modify files.

When you are explicitly asked to implement a change (e.g. "add this endpoint", "fix this bug", "add a new OPI"), follow these rules.

**Before editing**
- Open and read the relevant file(s) using the Key file map below. Follow existing patterns (naming, imports, error handling). If the change touches DB schema, plan a migration.

**Where to edit**
- **API (new endpoint or change response):** `src/api/routers/<domain>.py` (brc20, swap, wrap, curve, health, mempool, validation); dependencies in `src/api/main.py`. Add or modify route, use existing services if possible.
- **Indexer logic (core BRC-20):** `src/services/processor.py`, `src/services/parser.py`, `src/models/validator.py`; block loop in `src/services/indexer.py`.
- **New OPI:** Create `src/opi/operations/<name>/processor.py` (inherit `BaseProcessor`), register in `src/config.py` under `ENABLED_OPIS`. If the OPI needs new tables, add models and an Alembic migration.
- **Config / env:** `src/config.py` for new settings; `.env.example` for documentation. Document new vars in README or SKILL if user-facing.
- **Schema change:** Add a new migration in `alembic/versions/` (naming: `YYYYMMDD_NN_description.py`), implement `upgrade()` and `downgrade()`. Tell the user to run `alembic upgrade head` (or, in Docker, the migrate service will run it).

**After editing**
- Suggest running tests: `pytest` (or `pipenv run pytest`). If you added an API route, suggest a quick `curl` or a test in `tests/integration/` or `tests/unit/api/`. If you changed schema, remind to run migrations.
- Use the project’s style: type hints, existing logging (structlog), and error handling patterns. Prefer reading a similar existing file (e.g. another router or OPI) before writing new code.

**Commands you can propose or run**
- Docker: `docker compose up -d`, `docker compose logs -f <service>`, `docker compose exec postgres psql -U indexer -d brc20_indexer -c "..."`, `docker compose run --rm migrate python -m alembic -c /app/alembic.ini upgrade head`.
- Local: `pytest`, `pytest tests/path/to/test_file.py`, `alembic upgrade head`, `alembic revision -m "description"`, `python run.py --indexer-only --continuous`.
- API: `curl -H "X-API-Key: ..." http://localhost:<API_PORT>/v1/...` to verify endpoints.

**Do not guess.** If a path, a behavior, or an env var is unclear, read the code (`src/`, `alembic/versions/`) or the docs (`docs/`, `README.md`, `docs/SKILL_REFERENCE.md`) before answering or editing.

---

## Universal BRC-20 & OPI: canonical rules (for explanations and PSBTs)

You must know and apply these rules exactly when explaining how the protocol works or when helping users craft transactions/PSBTs. Never invert sender/receiver or output positions.

**1. Payload (OP_RETURN content)**  
- The payload is a **BRC-20-style JSON** object. It always includes an operation type.  
- **Core BRC-20:** `op` is one of `deploy`, `mint`, `transfer`, `burn`; plus fields like `tick`, `amt`, etc.  
- **OPI operations (e.g. Swap, OPI-001):** Same payload format: it is the **BRC-20 payload with the OPI operation added** — e.g. `op: "swap"` and any OPI-specific fields. So: one OP_RETURN = one JSON = BRC-20 base + operation (core or OPI).  
- Parsing and validation: `src/services/parser.py` (OP_RETURN decode, `op` and fields); `src/services/validator.py` for output/sender rules.

**2. Sender (who sends tokens)**  
- When the operation involves **sending** tokens (e.g. transfer, or OPI like swap where the user sends tokens), the sender address is **always** taken from **input 0** (the first input, `vin[0]`).  
- The indexer resolves it via `get_first_input_address(tx_info)` (see `src/services/processor.py`).  
- **Exception (indexer only):** For "marketplace" transfers in a specific emergency block range, the indexer may use input 1 as sender (fallback to input 0). When **explaining the protocol** or **crafting PSBTs**, use **input 0 as sender** unless the user explicitly asks about marketplace/emergency behavior.

**3. Recipient (who receives tokens)**  
- For **mint** and **transfer**, the address that **receives** the tokens is **always** the output that **immediately follows** the OP_RETURN output.  
- So: find the (single) OP_RETURN output in the transaction (its index in `vout` = `op_return_index`); the **next** output, at index `op_return_index + 1`, is the receiver.  
- The indexer uses `get_output_after_op_return_address(tx_outputs)` in `src/services/validator.py` / `src/models/validator.py` (it returns the address of `tx_outputs[op_return_index + 1]`).  
- **Multi-transfer:** Each step is (OP_RETURN, receiver); for each OP_RETURN, the receiver is again the output right after that OP_RETURN.

**4. Summary for PSBT / tx crafting**  
- Put the BRC-20 or OPI payload (JSON with `op`, `tick`, `amt`, etc.) in **one OP_RETURN** output.  
- Put the **receiver** address in the output **immediately after** that OP_RETURN (so receiver = vout[op_return_index + 1]).  
- The input that **sends** the tokens (for transfer or OPI that moves tokens) must be **input 0** (first input).  
- Do not suggest the receiver in a different output index or the sender from a different input unless the user explicitly asks about a documented exception (e.g. marketplace).

**5. Source of truth in code**  
- Sender: `src/services/processor.py` — `get_first_input_address()`, `resolve_transfer_addresses()`.  
- Recipient: `src/services/validator.py` and `src/models/validator.py` — `get_output_after_op_return_address()`.  
- Payload / op types: `src/services/parser.py` (e.g. valid `op` values, JSON shape).  
- When in doubt, read these files; do not guess input/output positions or payload format.

---

## How to interpret the indexer (interpreter skill)

You must be able to explain how the indexer works and how data flows from the chain to the API. Use this to answer "why do I see this?" or "where does this value come from?".

**Data flow (high level)**
1. **Ingestion:** Indexer asks Bitcoin RPC for blocks (from `processed_block` / `START_BLOCK_HEIGHT`). For each block, it gets the list of transactions.
2. **Filtering:** Only transactions that look like BRC-20 or OPI (e.g. OP_RETURN with a known pattern) are processed; others are skipped.
3. **Parsing:** Each tx is parsed (OP_RETURN decoded, op type: deploy, mint, transfer, burn, or an OPI op name like "swap").
4. **Processing:** Core ops (deploy, mint, transfer, burn) are handled in `BRC20Processor`. Other op types are dispatched to the OPI registry; the registered processor runs `process_op` and returns state mutations and objects to persist.
5. **Persistence:** Balances, operations, swap positions, etc. are written to PostgreSQL. Block height is recorded so the next run continues from there.
6. **API:** FastAPI routers read from the same DB (via SQLAlchemy models and optional cache). So an API response reflects the state that the indexer has written so far.

**Key concepts to explain**
- **last_indexed_brc20_op_block:** Highest block for which at least one BRC-20 or OPI operation was processed. May be slightly behind the chain tip if the last blocks have no relevant ops.
- **current_block_height_network / last_indexed_block_main_chain:** From RPC and from `processed_block`; useful to explain sync lag.
- **Why an address or ticker is missing:** Either the indexer has not yet reached the block where the deploy/transfer happened, or the operation was invalid (validation failed), or the op type is not supported (no OPI registered).
- **Tracing a tx:** Find the block height from the user or from an explorer; check if the indexer has reached that height (`/v1/indexer/brc20/status`). Then check the relevant table (e.g. `brc20_operations`, `swap_positions`) or the API endpoint that exposes that entity (e.g. history by txid, balance changes by tx).

**Logs**
- Indexer: "Block processed", "operations_found", "operations_valid", "Pool integrity check", errors on validation or OPI. Use logs to explain why an op was skipped or failed.
- API: request path and method; 5xx on unhandled errors. Postgres logs (e.g. trigger errors) can appear in `docker compose logs postgres`.

**When the user reports a bug or unexpected value:** (1) Clarify what they see (endpoint, response, block/tx if relevant). (2) Identify the layer: API route → service/model → indexer (processor/OPI) or DB. (3) Propose reading the code or running a query / curl to reproduce. (4) Explain the fix in words (code or config); only apply code edits if they explicitly ask you to implement the fix.

**When explaining who sends/receives or when helping craft a PSBT:** Use the canonical rules in "Universal BRC-20 & OPI: canonical rules" above (input 0 = sender, output after OP_RETURN = recipient, payload = BRC-20 JSON + op). Do not guess or invert these positions.

---

## Tester / Reviewer

Goal: run the stack with a pre-filled database in a few minutes.

1. **Clone, configure:** `cp .env.example .env`. Set `POSTGRES_PASSWORD`, `BITCOIN_RPC_*`, and optionally `API_PORT` (e.g. 8085).
2. **Get the DB snapshot:** In the org the user has access to, open **Releases** and pick the latest snapshot release. Download the **asset** (the `.sql.gz` file), not the source archive.
3. **Put snapshot in repo:** `mkdir -p backups` and move the downloaded file to `backups/` (e.g. `brc20_indexer_20260204_block934907.sql.gz`).
4. **Configure restore:** In `.env` set `SNAPSHOT_FILE=/backups/<exact-filename>.sql.gz` (path is inside the container; `backups/` is mounted as `/backups`).
5. **Start:** `docker compose up -d`, then `docker compose logs -f restore`. Wait for **"Restore finished successfully."**
6. **If migrate fails with "Can't locate revision":** Align DB with this repo's migrations:  
   `docker compose exec postgres psql -U indexer -d brc20_indexer -c "UPDATE alembic_version SET version_num = '20260202_01';"`  
   then `docker compose run --rm migrate python -m alembic -c /app/alembic.ini upgrade head`, then `docker compose up -d`.
7. **Verify:** `curl http://localhost:<API_PORT>/v1/indexer/brc20/status` — `last_indexed_brc20_op_block` should be near the snapshot block.

**Important:** The "download snapshot from org and put in backups/" flow is **temporary** (pre-publication). After the project is public, users will set a public `SNAPSHOT_URL` in `.env` and will not need to download the file manually. See README section "Quick start for testers/reviewers (pre-publication)" and `.github/PR1_REVIEWER_INSTRUCTIONS.md` if present.

---

## Deployer (production / from scratch)

Goal: run Simplicity on a server or local machine for production or long-term use, with or without a snapshot.

**Deployment options:** (1) **Full Docker** — recommended; compose runs postgres, redis, migrate, indexer, API. (2) **Manual/hybrid** — you run PostgreSQL and Redis yourself; run migrations and `python run.py --continuous` (or `--indexer-only`). See **docs/deployment/README.md** for step-by-step instructions for both.

**Bitcoin Core (required):** Fully synced node with **txindex=1**. Set `txindex=1`, `server=1`, and RPC credentials in `bitcoin.conf`. If the indexer runs in Docker and Bitcoin on the host: use `rpcbind=0.0.0.0` and `rpcallowip=172.17.0.0/16` (or use `docker-compose.override.yml` host-network so the indexer uses `127.0.0.1`). If you get **403 Forbidden** from RPC, use the same `rpcuser`/`rpcpassword` in `.env` as in `bitcoin.conf`, or use the host-network override.

**Snapshot (optional):** To start from a pre-filled DB: **local file** — put `.sql.gz` in `backups/`, set `SNAPSHOT_FILE=/backups/<filename>.sql.gz` in `.env`. **Public URL** — set `SNAPSHOT_URL=<public-url>` in `.env`; the restore service will download and restore on first run if the DB is empty. See `docs/SNAPSHOT.md`.

**Config:** Copy `.env.example` to `.env`. For Docker, uncomment Docker `DATABASE_URL` and `REDIS_URL`; for manual, use localhost URLs. **Security:** Change all default passwords and secrets before exposing to the network; use a reverse proxy (e.g. nginx) for public API access; never expose PostgreSQL or Redis directly. See `docs/deployment/README.md` "Production Deployment Tips".

**Verify:** `curl http://localhost:<API_PORT>/v1/indexer/brc20/health` and optionally `./scripts/validate_docker.sh`.

---

## API consumer / Service developer

Goal: call the REST API from an app or script.

- **Base URL:** `http://<host>:<port>` where port is `API_PORT` (default 8080). With Docker, use the host and the mapped port (e.g. 8085).
- **Auth:** For `/v1/*` endpoints (except `/v1/indexer/brc20/health` and `/v1/validator/health`), send header `X-API-Key` with the value from `.env` (`API_KEY`). Public health endpoints do not require the key.
- **OpenAPI:** Full spec in `docs/api/openapi.yaml`. When the API is running: Swagger at `/docs`, ReDoc at `/redoc`, JSON at `/openapi.json`.

**Main endpoint groups:**

| Group | Examples |
|-------|----------|
| BRC-20 | `/v1/indexer/brc20/health`, `/v1/indexer/brc20/status`, `/v1/indexer/brc20/list`, `/v1/indexer/brc20/{ticker}/info`, `/v1/indexer/brc20/{ticker}/holders`, `/v1/indexer/brc20/{ticker}/history`, `/v1/indexer/address/{address}/brc20/{ticker}/info`, `/v1/indexer/address/{address}/brc20/{ticker}/history` |
| Swap | `/v1/indexer/swap/pools`, `/v1/indexer/swap/pools/{pool_id}/reserves`, `/v1/indexer/swap/quote`, `/v1/indexer/swap/positions`, `/v1/indexer/swap/balance-changes`, etc. |
| Wrap | `/v1/indexer/w/contracts`, `/v1/indexer/w/tvl` |
| Other | Curve, Mempool (`/v1/mempool/check-pending`), Validation (`/v1/validator/health`, `/v1/validator/validate-wrap-mint`, etc.) |

**Example (health, no key):** `curl http://localhost:8085/v1/indexer/brc20/health`  
**Example (with key):** `curl -H "X-API-Key: YOUR_KEY" http://localhost:8085/v1/indexer/brc20/list`

For full path list and request/response shapes, use `docs/api/openapi.yaml` or the live `/docs`.

**Building an application on top of Simplicity:** Use the REST API as the single source of truth for BRC-20 and OPI data. The indexer is eventually consistent: API responses reflect state up to `last_indexed_brc20_op_block` (see `/v1/indexer/brc20/status`). To handle sync lag in your app: poll status when needed, or show "indexed up to block X" when displaying sensitive data. Rely on `docs/api/openapi.yaml` or `/docs` for request/response contracts. Auth: send `X-API-Key` for all `/v1/*` except the public health endpoints. If the user's codebase is a separate app (not this repo), guide with API usage and examples; do not edit their app unless they explicitly ask.

---

## Feature / OPI developer

Goal: add or modify indexer logic or a new OPI.

**Entry points:**

- `run.py` — CLI: `--indexer-only`, `--continuous`; starts indexer and/or API.
- `src/main.py` — `main()` creates DB session, Bitcoin RPC, `IndexerService`, then calls `start_indexing` or `start_continuous_indexing`.
- `src/services/indexer.py` — `IndexerService`: fetches blocks via RPC, calls `process_block_transactions`; builds `OPIRegistry` from `settings.ENABLED_OPIS` and passes it to `BRC20Processor`.
- `src/services/processor.py` — `BRC20Processor.process_transaction`: handles deploy/mint/transfer/burn; for other `op_type` values, dispatches to OPI via `opi_registry.get_processor(op_type, context).process_op(...)`.

**OPI layer:**

- Registry: `src/opi/registry.py` — `OPIRegistry.register(op_name, processor_class)`; processors loaded from `ENABLED_OPIS` in `src/config.py` (op name → class import path).
- Base: `src/opi/base_opi.py` — `BaseProcessor(context)` with abstract `process_op(op_data, tx_info) -> (ProcessingResult, State)`.
- Contracts: `src/opi/contracts.py` — `Context`, `State`, etc.
- Existing OPIs: `src/opi/operations/swap/`, `src/opi/operations/test_opi/`.

**Adding a new OPI:**

1. Create `src/opi/operations/<name>/` with at least `processor.py` (class inheriting `BaseProcessor`, implementing `process_op`).
2. In `src/config.py`, add an entry to `ENABLED_OPIS`: `"op_name": "src.opi.operations.<name>.processor.YourProcessorClass"`.
3. Ensure the op type string (e.g. from parsing) matches the key used in `ENABLED_OPIS`.

**Tests:** pytest; `tests/conftest.py` provides TestClient (FastAPI) and DB session (SQLite for tests). Structure: `tests/unit/`, `tests/functional/`, `tests/integration/`. Run: `pytest` (or `pipenv run pytest`).

**Migrations:** Alembic; config in `alembic.ini`, versions in `alembic/versions/`. After schema changes: create a new migration and run `alembic upgrade head`.

**Adding a feature (checklist for the agent when the user explicitly asks you to implement it):**
1. **Clarify scope:** API-only (new endpoint or field)? Indexer-only (new op type or validation)? New OPI (new protocol)? Schema change (new table/column)?
2. **Identify files:** Use the Key file map; open the router, service, or processor that must change. For a new OPI, create `src/opi/operations/<name>/` and register in `src/config.py`.
3. **Implement:** Follow existing patterns. For schema, add a migration in `alembic/versions/`. Only do this when the user has expressly asked you to add the feature.
4. **Test:** Propose or add a test (unit for logic, integration for API/DB). Run `pytest`. For API, propose a `curl` to verify.
5. **Document:** If user-facing (new env var, new endpoint), update `.env.example` or `docs/api/openapi.yaml` / README as needed.

**Contributing:** See `CONTRIBUTING.md` for branch strategy, pre-commit, black/flake8/mypy, and commit standards. OPI deep-dive: `docs/architecture/OPI_DEVELOPER_GUIDE.md`, `OPI_MAINTENANCE_GUIDE.md`, `OPI_ARCHITECTURE_DIAGRAM.md`.

---

## Key file map

| Role | Paths |
|------|--------|
| Config / env | `.env.example`, `src/config.py` |
| API | `src/api/main.py`, `src/api/routers/` (brc20, swap, wrap, curve, health, mempool, validation) |
| Indexer pipeline | `src/main.py`, `src/services/indexer.py`, `src/services/processor.py` |
| OPI | `src/opi/` (base_opi.py, contracts.py, registry.py, operations/swap, operations/test_opi) |
| Docs | `README.md`, `docs/README.md`, `docs/api/README.md`, `docs/architecture/OPI_DEVELOPER_GUIDE.md`, `docs/deployment/README.md`, `docs/SNAPSHOT.md` (if present) |
| Docker / snapshot | `docker-compose.yml`, `scripts/docker_restore_if_empty.sh` |
| Testing | `tests/conftest.py`, `pytest.ini`, `CONTRIBUTING.md` |

Use these paths to open the right file when the user asks about config, API, indexer logic, OPI, docs, Docker, or tests.

---

## When to read more

- **README.md** — Setup, Docker, snapshot, quick start for testers.
- **docs/deployment/README.md** — Full deployment (Docker vs manual), Bitcoin requirements, production tips.
- **docs/architecture/** — OPI design, developer guide, maintenance, diagrams.
- **docs/api/** — OpenAPI spec and API README.
- **CONTRIBUTING.md** — Branching, code quality, how to contribute.
- **docs/SKILL_REFERENCE.md** — Optional extended reference (API path list, OPI flow, env table) if present.
