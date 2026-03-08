#!/usr/bin/env bash
# End-to-end validation of the Dockerized Simplicity stack.
# Run after: cp .env.example .env, fill .env, then docker-compose up -d
#
# Usage: ./scripts/validate_docker.sh [--start]
#   --start: run docker-compose up -d before validating (default: assume stack is already up)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DO_START=false
for arg in "$@"; do
  [ "$arg" = "--start" ] && DO_START=true
done

echo "=== Simplicity Docker validation ==="

# 1. .env exists and required vars
if [ ! -f .env ]; then
  echo "Error: .env not found. Copy .env.example to .env and set POSTGRES_PASSWORD, BITCOIN_RPC_URL (and RPC auth)." >&2
  exit 1
fi

if ! grep -q '^POSTGRES_PASSWORD=' .env 2>/dev/null || ! grep -q '^BITCOIN_RPC_URL=' .env 2>/dev/null; then
  echo "Error: .env must define POSTGRES_PASSWORD and BITCOIN_RPC_URL (non-empty, uncommented)." >&2
  exit 1
fi
echo "  .env present, POSTGRES_PASSWORD and BITCOIN_RPC_URL set."

# API port: from .env or default 8080 (docker-compose uses API_PORT for host mapping)
API_PORT=8080
if grep -q '^API_PORT=' .env 2>/dev/null; then
  API_PORT=$(grep '^API_PORT=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")
fi
API_BASE="http://localhost:${API_PORT}"

# 2. Optional start
if [ "$DO_START" = true ]; then
  echo "  Starting stack (docker-compose up -d)..."
  docker-compose up -d
  echo "  Waiting for Postgres and Redis to be healthy..."
  sleep 5
fi

# 3. Wait for API health (container may still be starting)
echo "  Waiting for API at $API_BASE (up to 120s)..."
for i in $(seq 1 120); do
  if curl -sf "$API_BASE/health" >/dev/null 2>&1; then
    echo "  API is up."
    break
  fi
  if [ "$i" -eq 120 ]; then
    echo "Error: API did not become healthy in time. Check: docker-compose logs api" >&2
    exit 1
  fi
  sleep 1
done

# 4. Health and status endpoints
echo ""
echo "--- Health ---"
curl -sf "$API_BASE/health" | head -c 200
echo ""

echo ""
echo "--- BRC-20 indexer health ---"
curl -sf "$API_BASE/v1/indexer/brc20/health" | head -c 200
echo ""

echo ""
echo "--- Indexer status (block heights) ---"
if curl -sf "$API_BASE/v1/indexer/brc20/status" 2>/dev/null; then
  echo ""
else
  echo "(endpoint may return 500 if indexer has not yet written any block; check indexer logs)"
fi

# 5. Indexer logs (last lines) – RPC and DB errors
echo ""
echo "--- Last indexer log lines (check for Bitcoin RPC or DB errors) ---"
docker-compose logs --tail=30 indexer 2>/dev/null || true

echo ""
echo "=== Validation done. If indexer logs show 'Bitcoin RPC' connection errors, check BITCOIN_RPC_URL is reachable from the container (e.g. host.docker.internal:8332 or external URL). ==="
