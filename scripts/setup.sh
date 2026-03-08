#!/usr/bin/env bash
# Simple onboarding: ask a few questions and prepare .env + override so "docker compose up -d" works.
# Usage: ./scripts/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Simplicity – quick setup ==="
echo ""

# 1) .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
else
  echo ".env already exists"
fi

# 2) Bitcoin RPC on this machine?
echo ""
echo "Is Bitcoin Core (or your RPC node) running on THIS machine? (y/n)"
echo "  y = use 127.0.0.1 (recommended if bitcoind is local; avoids 403)"
echo "  n = use external RPC URL, or install Bitcoin Core in Docker (~750GB)"
read -r BITCOIN_LOCAL

USE_OVERRIDE=false
USE_BITCOIND_DOCKER=false

if [ "$BITCOIN_LOCAL" = "y" ] || [ "$BITCOIN_LOCAL" = "Y" ]; then
  USE_OVERRIDE=true
  if [ ! -f docker-compose.override.yml ]; then
    cp docker-compose.override.yml.example docker-compose.override.yml
    echo "Created docker-compose.override.yml (indexer will use 127.0.0.1 for RPC, Postgres, Redis)"
  fi
  if grep -q '^BITCOIN_RPC_URL=' .env; then
    sed -i.bak 's|^BITCOIN_RPC_URL=.*|BITCOIN_RPC_URL=http://127.0.0.1:8332|' .env 2>/dev/null || true
  fi
else
  # Bitcoin not on this machine: verify disk space, then offer Docker install only if >= 750 GB
  echo ""
  echo "Checking free space for optional Bitcoin Core in Docker (need ~750 GB)..."
  NEED_KB=$((750 * 1024 * 1024))
  AVAIL_KB=""
  if command -v df >/dev/null 2>&1; then
    AVAIL_KB=$(df -k . 2>/dev/null | awk 'NR==2 {print $4}')
  fi
  if [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -ge "$NEED_KB" ] 2>/dev/null; then
    AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
    echo "Free space: ~${AVAIL_GB} GB (enough for Bitcoin in Docker)."
    echo "Install Bitcoin Core in Docker? (chain sync from scratch, ~750 GB) (y/n)"
    read -r INSTALL_BITCOIND
    if [ "$INSTALL_BITCOIND" = "y" ] || [ "$INSTALL_BITCOIND" = "Y" ]; then
      USE_BITCOIND_DOCKER=true
      if ! grep -q '^BITCOIN_RPC_USER=' .env 2>/dev/null || grep -q '^BITCOIN_RPC_USER=your_rpc_user$' .env; then
        sed -i.bak 's/^BITCOIN_RPC_USER=.*/BITCOIN_RPC_USER=bitcoin/' .env 2>/dev/null || true
      fi
      if ! grep -q '^BITCOIN_RPC_PASSWORD=.\+' .env 2>/dev/null || grep -q '^BITCOIN_RPC_PASSWORD=your_rpc_password$' .env; then
        echo "Set a password for Bitcoin RPC (stored in .env):"
        read -rs RPC_PW
        echo ""
        [ -n "$RPC_PW" ] && sed -i.bak "s/^BITCOIN_RPC_PASSWORD=.*/BITCOIN_RPC_PASSWORD=$(echo "$RPC_PW" | sed 's/[[\.*^$()+?{|]/\\&/g')/" .env 2>/dev/null || true
      fi
      sed -i.bak 's|^BITCOIN_RPC_URL=.*|BITCOIN_RPC_URL=http://bitcoind:8332|' .env 2>/dev/null || true
      echo "Configured .env for Bitcoin Core in Docker (BITCOIN_RPC_URL=http://bitcoind:8332)."
    fi
  else
    if [ -n "$AVAIL_KB" ]; then
      AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
      echo "Free space: ~${AVAIL_GB} GB — need ~750 GB for Bitcoin in Docker."
    else
      echo "Could not read disk space; ensure ~750 GB free if you plan to run Bitcoin in Docker."
    fi
    echo "Set BITCOIN_RPC_URL in .env to your external RPC or host.docker.internal:8332"
  fi
fi

# 3) Required: POSTGRES_PASSWORD
echo ""
if ! grep -q '^POSTGRES_PASSWORD=.\+' .env 2>/dev/null || grep -q '^POSTGRES_PASSWORD=indexer_password$' .env; then
  echo "Set a password for Postgres (will be written to .env):"
  read -rs POSTGRES_PW
  echo ""
  if [ -n "$POSTGRES_PW" ]; then
    sed -i.bak "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(echo "$POSTGRES_PW" | sed 's/[[\.*^$()+?{|]/\\&/g')/" .env 2>/dev/null || true
    echo "POSTGRES_PASSWORD updated in .env"
  fi
fi

# 4) RPC credentials (reminder)
echo ""
echo "Ensure in .env: BITCOIN_RPC_USER and BITCOIN_RPC_PASSWORD (or cookie) match your node."
echo "Edit .env now if needed: vi .env"
echo ""

# 5) Optional: API port (avoid 8080 conflict)
if grep -q '^API_PORT=8080$' .env 2>/dev/null; then
  echo "Use a different API port than 8080 to avoid conflicts? (e.g. 8085) [leave empty to keep 8080]:"
  read -r API_PORT
  if [ -n "$API_PORT" ]; then
    sed -i.bak "s/^API_PORT=.*/API_PORT=$API_PORT/" .env 2>/dev/null || true
    echo "API_PORT=$API_PORT set in .env"
  fi
fi

rm -f .env.bak 2>/dev/null || true

echo ""
echo "=== Setup done ==="
if grep -q '^BITCOIN_RPC_URL=http://bitcoind:8332' .env 2>/dev/null; then
  echo "Start the stack (with Bitcoin Core in Docker):"
  echo "  docker compose --profile bitcoind up -d"
  echo ""
  echo "Bitcoind will sync the chain (~750GB). Indexer will connect once RPC is ready."
else
  echo "Start the stack:"
  echo "  docker compose up -d"
fi
echo ""
echo "Then check: docker compose logs -f indexer   and   curl http://localhost:\${API_PORT:-8080}/health"
echo ""
