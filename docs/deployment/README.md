# Simplicity Indexer Deployment Guide

## Quick Start

### 1. Docker Compose (Recommended)
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env`:
   - Set your Bitcoin Core RPC credentials.
   - Uncomment the Docker-specific `DATABASE_URL` and `REDIS_URL` lines, comment out the localhost versions.
   - Change all default passwords and secrets if deploying beyond localhost.
3. Start all services:
   ```bash
   docker-compose up -d
   ```
4. Check health:
   ```bash
   curl http://localhost:8080/v1/indexer/brc20/health
   ```

### 2. Manual/Hybrid
1. Copy `.env.example` to `.env` and edit as above, but use the localhost `DATABASE_URL` and `REDIS_URL`.
2. Install dependencies (pipenv or requirements.txt), run migrations, and start the indexer:
   ```bash
   pip install pipenv
   pipenv install --dev
   pipenv run alembic upgrade head
   pipenv run python run.py --continuous
   # Or use requirements.txt and python run.py --continuous
   ```

> **Security Warning:**
> If you expose any service to the internet, you MUST change all default passwords and users in your `.env` and in `docker-compose.yml`. Never expose PostgreSQL or Redis directly to the internet.

---

## Bitcoin Core Requirements (Required for All Deployments)

- You must have a fully synced Bitcoin Core full node with transaction indexing enabled.
- **Bitcoin Core version:** 24.x or later recommended (older versions may work but are not tested).
- **Configuration:** Edit your `bitcoin.conf` (usually in `~/.bitcoin/bitcoin.conf`) to include:
  ```
  txindex=1
  server=1
  rpcuser=your_rpc_user
  rpcpassword=your_rpc_password
  rpcbind=127.0.0.1
  rpcallowip=127.0.0.1
  ```
- **Start Bitcoin Core** and wait for it to fully sync.
- **Verify status:**
  ```bash
  bitcoin-cli getblockchaininfo
  bitcoin-cli getindexinfo
  ```
  Ensure `txindex` is enabled and fully synced.
- **The indexer will not work without a running, fully synced Bitcoin node with `txindex=1`.**

---

## Deployment Methods

There are two main ways to deploy Simplicity Indexer:

---

## 1. **Full Docker Deployment (Recommended)**
- **You provide:** A running Bitcoin Core full node (with `txindex=1`), accessible from the Docker host.
- **Docker Compose manages:** PostgreSQL, Redis, and the Indexer.

### Steps
1. **Ensure your Bitcoin node is running and fully synced.**
2. **Clone the repository:**
   ```bash
   git clone https://github.com/The-Universal-BRC20-Extension/simplicity.git
   cd simplicity
   ```
3. **Copy and edit the environment file:**
   ```bash
   cp .env.example .env
   # Edit .env to set your Bitcoin RPC credentials (BITCOIN_RPC_URL, BITCOIN_RPC_USER, BITCOIN_RPC_PASSWORD)
   # Uncomment Docker DATABASE_URL and REDIS_URL, comment out localhost versions.
   # Change all default passwords and secrets if deploying beyond localhost.
   ```
4. **Start all services:**
   ```bash
   docker-compose up -d
   # Check health
   curl http://localhost:8080/v1/indexer/brc20/health
   ```

**Note:**
- PostgreSQL and Redis are started as containers.
- The indexer connects to them using the service names (`postgres`, `redis`) as hostnames.
- No need to install Python dependencies or services manually.

---

## 2. **Manual/Hybrid Deployment**
- **You provide:**
  - A running Bitcoin Core full node (with `txindex=1`)
  - A running PostgreSQL database (on your host or elsewhere)
  - Redis (either installed locally or run as a Docker container)
  - Python 3.11+ and pipenv (or requirements.txt)

### Steps
1. **Ensure your Bitcoin node is running and fully synced.**
2. **Install and start PostgreSQL.**
   - Create the database and user as described below.
3. **Install and start Redis.**
   - Option 1: Install Redis locally (see [official docs](https://redis.io/download)).
   - Option 2: Run Redis as a container:
     ```bash
     docker run -d --name redis -p 6380:6379 redis:6-alpine
     # Redis will be available at redis://localhost:6380/0
     ```
4. **Clone the repository:**
   ```bash
   git clone https://github.com/The-Universal-BRC20-Extension/simplicity.git
   cd simplicity
   ```
5. **Copy and edit the environment file:**
   ```bash
   cp .env.example .env
   # Set BITCOIN_RPC_URL, BITCOIN_RPC_USER, BITCOIN_RPC_PASSWORD
   # Set DATABASE_URL to your Postgres instance (e.g. postgresql://indexer:password@localhost:5432/brc20_indexer)
   # Set REDIS_URL to your Redis instance (e.g. redis://localhost:6380/0 if using Docker)
   # Change all default passwords and secrets if deploying beyond localhost.
   ```
6. **Install Python dependencies:**
   - With pipenv (recommended):
     ```bash
     pip install pipenv
     pipenv install --dev
     pipenv shell
     ```
   - Or with requirements.txt:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     pip install -r requirements.txt
     ```
7. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```
8. **Start the indexer:**
   ```bash
   pipenv run python run.py --continuous
   # Or, if using requirements.txt: python run.py --continuous
   ```

---

## Testing Your Setup

After starting the indexer, check the health endpoint:
```bash
curl http://localhost:8080/v1/indexer/brc20/health
# Expected output: { "status": "ok" }
```

If you see errors, check your `.env` configuration and ensure all services are running.

---

## Production Deployment Tips
- Expose services only on localhost by default.
- Use a reverse proxy (e.g., nginx) for public access.
- Never expose PostgreSQL or Redis directly to the internet.
- Always change all default passwords and secrets before deploying publicly.

For more, see the main [README.md](../../README.md). 