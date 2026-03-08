# SKILL reference – API paths, OPI flow, env vars

Extended reference for the agent when details are needed. Main guidance is in [SKILL.md](../SKILL.md).

---

## API paths (by group)

All under base URL `http://<host>:<API_PORT>`. Auth: `X-API-Key` for `/v1/*` except `/v1/indexer/brc20/health` and `/v1/validator/health`.

### Root and health

- `GET /` — root
- `GET /health/concurrency`
- `GET /v1/indexer/brc20/health` — public
- `GET /v1/validator/health` — public

### BRC-20

- `GET /v1/indexer/brc20/status`
- `GET /v1/indexer/brc20/list`
- `GET /v1/indexer/brc20/list/all`
- `GET /v1/indexer/brc20/{ticker}/info`
- `GET /v1/indexer/brc20/{ticker}/holders`
- `GET /v1/indexer/brc20/{ticker}/holders/all`
- `GET /v1/indexer/brc20/{ticker}/history`
- `GET /v1/indexer/brc20/history/all`
- `GET /v1/indexer/brc20/{ticker}/tx/{txid}/history`
- `GET /v1/indexer/brc20/history-by-height/{height}`
- `GET /v1/indexer/brc20/history-by-height/{height}/all`
- `GET /v1/indexer/address/{address}/brc20/{ticker}/info`
- `GET /v1/indexer/address/{address}/history`
- `GET /v1/indexer/address/{address}/history/all`
- `GET /v1/indexer/address/{address}/brc20/{ticker}/history`
- `GET /v1/indexer/address/{address}/brc20/{ticker}/history/all`

### Mempool and validation

- `GET /v1/mempool/check-pending`
- `POST /v1/validator/validate-wrap-mint`
- `POST /v1/validator/validate-address-from-witness`

### Swap

- `GET /v1/indexer/swap/positions`
- `GET /v1/indexer/swap/tvl/{ticker}`
- `GET /v1/indexer/swap/pools`
- `GET /v1/indexer/swap/pools/{pool_id}/reserves`
- `GET /v1/indexer/swap/quote`
- `GET /v1/indexer/swap/pools/{pool_id}/transactions`
- `GET /v1/indexer/swap/positions/{position_id}`
- `GET /v1/indexer/swap/owner/{owner}/positions`
- `GET /v1/indexer/swap/expiring`
- `GET /v1/indexer/swap/executions`
- `GET /v1/indexer/swap/executions/{execution_id}`
- `GET /v1/indexer/swap/metrics/global`
- `GET /v1/indexer/swap/metrics/timeseries`
- `GET /v1/indexer/swap/metrics/top-executors`
- `GET /v1/indexer/swap/metrics/fill-rate`
- `GET /v1/indexer/swap/balance-changes` (with query params)
- `GET /v1/indexer/swap/balance-changes/{change_id}`
- `GET /v1/indexer/swap/balance-changes/tx/{txid}`
- `GET /v1/indexer/swap/balance-changes/position/{position_id}`
- `GET /v1/indexer/swap/balance-changes/operation/{operation_id}`
- `GET /v1/indexer/swap/balance-changes/address/{address}`
- `GET /v1/indexer/swap/balance-changes/aggregate`
- `GET /v1/indexer/swap/balance-changes/stats`
- `GET /v1/indexer/swap/balance-changes/verify/tx/{txid}`
- `GET /v1/indexer/swap/balance-changes/verify/operation/{operation_id}`
- `GET /v1/indexer/swap/balance-changes/pool/{pool_id}`

### Wrap

- `GET /v1/indexer/w/contracts`
- `GET /v1/indexer/w/contracts/{script_address}`
- `GET /v1/indexer/w/tvl`
- `GET /v1/indexer/w/metrics`

Full request/response schemas: `docs/api/openapi.yaml` or live `/docs`, `/openapi.json`.

---

## OPI flow (high level)

1. **Block ingestion** — `IndexerService` (in `src/services/indexer.py`) gets block from Bitcoin RPC and builds a list of transactions.
2. **Per transaction** — `BRC20Processor.process_transaction` (in `src/services/processor.py`) parses the tx and determines `op_type` (deploy, mint, transfer, burn, or an OPI op name).
3. **Core vs OPI** — If `op_type` is deploy/mint/transfer/burn, core logic runs. Otherwise, if `opi_registry.has_processor(op_type)`, the agent gets `processor = opi_registry.get_processor(op_type, context)` and calls `processor.process_op(operation_data, tx_info)`.
4. **State and persist** — OPI returns `(ProcessingResult, State)`; `State.state_mutations` are applied to `intermediate_state`; then the processor flushes balances and persists objects. Block is committed after all txs.

OPI registration: at indexer startup, `ENABLED_OPIS` (in `src/config.py`) is iterated; each entry is loaded with `importlib` and registered as `opi_registry.register(op_name, processor_class)`.

---

## Key environment variables

| Variable | Role |
|----------|------|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Postgres (Docker and migrate/indexer/api) |
| `DATABASE_URL` | Overridden in compose for services; used as-is for local runs |
| `BITCOIN_RPC_URL`, `BITCOIN_RPC_USER`, `BITCOIN_RPC_PASSWORD` | Bitcoin RPC (or `BITCOIN_RPC_COOKIE_FILE`) |
| `API_PORT` | Port for API (default 8080); used by Docker and uvicorn |
| `API_KEY` | Sent as `X-API-Key` for protected `/v1` endpoints |
| `REDIS_URL` | Cache (overridden in compose to `redis://redis:6379/0`) |
| `START_BLOCK_HEIGHT` | First block to index (e.g. 895534) |
| `SNAPSHOT_FILE` | Path in container to snapshot (e.g. `/backups/brc20_indexer_*.sql.gz`) |
| `SNAPSHOT_URL` | Public URL to download snapshot if DB empty |
| `ENABLED_OPIS` | Dict in config: op name → processor class path (e.g. `"swap": "src.opi.operations.swap.processor.SwapProcessor"`) |
| `SWAP_EXE_ACTIVATION_HEIGHT`, `STONES_ACTIVATION_HEIGHT`, etc. | Protocol activation heights |

See `.env.example` and `src/config.py` for the full list and defaults.
