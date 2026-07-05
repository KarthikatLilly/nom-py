# Phase 1 — Architecture Understanding

## What is NOM?

NOM is not a protocol. It's an infrastructure component.
NOM speaks MCP on both sides:
•	to the agent → it looks like an MCP server
•	to the real tools → it looks like an MCP client
But in the middle, NOM inserts logic that MCP itself doesn’t define:
•	authentication
•	authorization (who can do what)
•	policy enforcement
•	audit logging
•	rate limiting
•	guardrails on risky actions
•	routing to the right upstream
•	idempotency & revert
•	observability (metrics, tracing)


## Goal
Understand the Go NOM architecture and map every component to a Python (FastAPI) equivalent, so the Python prototype mirrors the same intent without literally translating Go code.

---

## 1. Entrypoint

| Aspect | Go NOM | nom-py |
|---|---|---|
| File | `main.go` | `app/main.py` |
| Server type | Go `net/http` | FastAPI + Uvicorn |
| Port | (from repo config) | 8001 |
| Routes registered so far | `/mcp`, `/connect`, `/register`, auth routes | `/health`, `/mcp` |

The Go binary boots via `cmd/`; Python boots via `uvicorn app.main:app`.

---

## 2. Core components

### Auth (from `internal/auth/oauth.go`, `store.go`)
- Go uses GitHub OAuth 2.0 (client_id, client_secret, callback).
- State/PKCE-like nonce stored in a `sync.Map` with TTL.
- Sessions persisted in a `Store`.
- **Python plan:** `app/auth/github_oauth.py` + `app/auth/state_store.py`.
- **Not implemented today** — planned for Phase 3.

### Policy (from `policy.yaml`, `aws.yaml`)
- YAML defines role-based allow/deny and platform-specific guardrails.
- Loaded at startup and applied in the request pipeline.
- **Python plan:** `app/policy/engine.py` compiles YAML → in-memory rules.
- **Not implemented today** — planned for Phase 3.

### MCP dispatch
- Go handles JSON-RPC methods like `initialize`, `tools/list`, `tools/call`.
- Each method has a switch case that routes to internal logic.
- **Python status today:** `app/api/routes/mcp.py` handles all 3 methods with stub responses.
- Real dispatcher planned in `app/mcp/dispatcher.py` — Phase 2.

### Logging / audit
- Go uses a `logger/` package with structured logs.
- **Python plan:** `app/observability/audit.py` for tool decisions + `logging.py` for structured logs.
- **Not implemented today** — planned for Phase 4.

---

## 3. Envoy-inspired concepts used

| Concept | Meaning | Where it lives in NOM |
|---|---|---|
| Filter chain | Ordered request interceptors (auth → policy → audit → route) | Middleware in `app/main.py` (future) |
| Upstream routing | Decide which backend gets the request | `app/mcp/registry.py` (future) |
| Observability | Access logs, tracing, metrics | `app/observability/` (future) |

Envoy is **only inspiration** — implementation is entirely different, done at Python/ASGI layer.

---

## 4. Python architecture plan

| Go component | Python equivalent |
|---|---|
| `main.go` | `app/main.py` |
| Route registration | `app/api/routes/` |
| Auth (`oauth.go`, `store.go`) | `app/auth/` |
| Policy (`policy.yaml`, `aws.yaml`) | `app/policy/` + `config/*.yaml` |
| MCP dispatch | `app/mcp/dispatcher.py` |
| Adapters to upstream MCP servers | `app/mcp/adapters/` |
| Logging / audit | `app/observability/` |
| Idempotency / compensation | `app/safety/` |

---

## 5. What today's prototype proves

- FastAPI serves JSON-RPC MCP responses correctly.
- `initialize` returns valid MCP capabilities (`protocolVersion`, `serverInfo`).
- The Swagger UI at `/docs` gives us an interactive tester for free.
- The scaffold is ready to receive real dispatch, auth, and policy logic.

---

## 6. Open questions

- Does the Go NOM keep a single upstream session or open one per client?
- How does `connectHandler.go` differ from the main `/mcp` handler?
- Does `register_handler.go` support dynamic server registration, or is it startup-only?
- How is user identity propagated to upstream MCP servers (pass-through vs NOM terminates)?
- What logging fields does the Go logger emit — do we need to match them for parity?