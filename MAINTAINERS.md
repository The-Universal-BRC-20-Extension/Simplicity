# Maintainer guide and handover

This document helps current and future maintainers run, release, and hand over the project.

## Quick run (for maintainers)

- Clone, `cp .env.example .env`, set `POSTGRES_PASSWORD` and `BITCOIN_RPC_*`.
- If Bitcoin Core is on the same machine: `cp docker-compose.override.yml.example docker-compose.override.yml`.
- `docker compose up -d`. API: `http://localhost:8080` (or `API_PORT` from `.env`).

Optional one-shot setup: `./scripts/setup.sh` then `docker compose up -d`.

## Releasing a database snapshot

1. Create a backup: from host with Postgres reachable (override: port 5433),
   ```bash
   export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=indexer PGPASSWORD=... PGDATABASE=brc20_indexer
   ./scripts/backup.sh
   ```
2. Upload the generated file from `backups/` to **GitHub Releases** (attach as asset) or to external storage.
3. Update the README or Release notes with the snapshot URL and restore instructions (see `docs/SNAPSHOT.md`).

## Adding maintainers

- Add GitHub usernames to **CODEOWNERS** (optional) and mention in README “Maintainers: …”.
- Document release and merge process in **CONTRIBUTING.md** (who can merge, how to cut a release).

## Handover checklist (when the main developer steps down)

- [ ] **README** is up to date: 5-minute setup, Docker, override, snapshot restore, troubleshooting (port 8080, 403).
- [ ] **.env.example** documents every variable; **scripts/setup.sh** and **scripts/restore_snapshot.sh** work and are referenced.
- [ ] **Releases**: at least one tagged release; snapshot (if any) linked as asset or URL.
- [ ] **Governance** in README: “Looking for maintainers”, link to CONTRIBUTING and MAINTAINERS.md.
- [ ] **Security**: no secrets in repo; SECURITY.md and dependency update process (e.g. Dependabot) if applicable.
- [ ] **Docs**: `docs/` (API, deployment, SNAPSHOT) and OpenAPI spec are current.

Keeping this file and CONTRIBUTING.md in sync ensures the project stays complete and simple for the next maintainer.
