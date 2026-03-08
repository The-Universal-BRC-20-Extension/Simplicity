# PR: External RPC providers (QuickNode, Alchemy) – API key auth

## Summary

This PR adds support for **external Bitcoin RPC providers** that use API-key or token-based authentication instead of HTTP Basic auth (user/password). Users can point the indexer at QuickNode, Alchemy, or any JSON-RPC endpoint that accepts a Bearer token, `x-token`, or `api-key` header.

**Branch:** `feature/external-rpc-providers`  
**Base:** `publish-cleanup` (or `main` when ready)

---

## What changed

| Area | Changes |
|------|--------|
| **Config** | `BITCOIN_RPC_API_KEY` (optional), `BITCOIN_RPC_AUTH_HEADER` (`Bearer` \| `x-token` \| `api-key`) |
| **RPC client** | `_RequestsRPCClient` accepts `extra_headers`; `_build_auth_headers()` builds headers with optional Basic auth and/or provider header |
| **Service** | When `BITCOIN_RPC_API_KEY` is set, auth mode is `api_key` and user/password are not required |
| **Docs** | README “External RPC providers” section; `.env.example` comments for QuickNode, Alchemy, Maestro (not compatible) |

No breaking changes: existing setups (Basic auth or cookie) are unchanged.

---

## Why tests are needed

- New code paths: `api_key` auth mode, `_build_auth_headers()`, and `extra_headers` in `_RequestsRPCClient`.
- Existing unit tests in `tests/unit/services/test_bitcoin_rpc.py` still patch `AuthServiceProxy`, while the service now uses `_RequestsRPCClient`; they may need to be updated to patch the correct class and to cover the new behaviour.

---

## Instructions for a contributor (or their agent)

**Goal:** Add and adjust tests so that the external RPC provider feature is covered and existing behaviour remains validated.

### 1. Scope of work

- **Update existing tests** in `tests/unit/services/test_bitcoin_rpc.py` so they match the current implementation (e.g. patch `src.services.bitcoin_rpc._RequestsRPCClient` instead of `AuthServiceProxy` where the service is under test). Fix or remove any test that relies on removed or renamed attributes (e.g. `connection_url` on the service).
- **Add unit tests** for:
  - **API key auth mode:** When `BITCOIN_RPC_API_KEY` is set (and optionally `BITCOIN_RPC_AUTH_HEADER`), the service initializes without requiring user/password and does not raise “username/password required”.
  - **Header construction:** For each of `BITCOIN_RPC_AUTH_HEADER` = `Bearer`, `x-token`, and `api-key`, the RPC client sends the expected header (e.g. `Authorization: Bearer <key>`, `x-token: <key>`, `api-key: <key>`) and no Basic auth when user/password are empty.
  - **No regression:** With user/password set and no API key, the client still sends Basic auth and no extra provider header.
- **Optional but welcome:** A small integration-style test that starts a local HTTP server (e.g. with `httptest` or a mock server) that expects a JSON-RPC `getblockcount` and checks that the request includes the expected auth header (Bearer / x-token / api-key) when API key is configured.

### 2. What the agent should do step by step

1. **Checkout the branch**  
   `git fetch origin feature/external-rpc-providers && git checkout feature/external-rpc-providers`

2. **Run existing tests**  
   From repo root:  
   `pipenv run pytest tests/unit/services/test_bitcoin_rpc.py -v`  
   Note any failures (e.g. wrong mock target or missing attributes).

3. **Inspect the implementation**  
   - `src/services/bitcoin_rpc.py`: `_build_auth_headers()`, `_RequestsRPCClient.__init__(..., extra_headers)`, and `BitcoinRPCService.__init__` (cookie vs api_key vs user_password).  
   - `src/config.py`: `BITCOIN_RPC_API_KEY`, `BITCOIN_RPC_AUTH_HEADER`.

4. **Update tests**  
   - Patch `src.services.bitcoin_rpc._RequestsRPCClient` where the test needs to avoid real HTTP (e.g. in `_get_rpc_connection`).  
   - Add tests for:
     - Service init with `BITCOIN_RPC_API_KEY` set (and no user/password): no ValueError, and `_extra_headers` or equivalent used when building the client.
     - For at least one header type (e.g. Bearer): verify that the request built by the client (or the headers passed to `_RequestsRPCClient`) contains the expected header and no Basic auth when user/password are empty.
   - Fix or remove tests that assume `AuthServiceProxy` or `connection_url` on the service.

5. **Run full unit test set**  
   `pipenv run pytest tests/unit/ -v`  
   Ensure all pass.

6. **Document briefly**  
   In the PR or in a short comment: list the new test names and what they cover (auth mode, header type, no Basic when API key is set).

### 3. Files to touch

- **Primary:** `tests/unit/services/test_bitcoin_rpc.py`  
  - Update mocks from `AuthServiceProxy` to `_RequestsRPCClient` where relevant.  
  - Add tests for API key auth and header construction; ensure Basic-auth-only path still tested.

- **Optional:** `tests/conftest.py` if a shared fixture for a mock HTTP JSON-RPC server is useful.

### 4. Out of scope for this PR

- Integration tests against real QuickNode/Alchemy endpoints (credentials and network).
- Changes to Maestro or other REST-only APIs (documented as not supported).

---

## Checklist for maintainer

- [ ] Feature code reviewed (config, `bitcoin_rpc.py`, docs).
- [ ] New/updated tests merged on this branch; CI passes.
- [ ] README and `.env.example` accuracy checked.
- [ ] No breaking change for existing envs (Basic auth / cookie).

---

*Copy the sections above into the GitHub PR description when opening the PR from `feature/external-rpc-providers`.*
