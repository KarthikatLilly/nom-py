# nom-py

> A Python (FastAPI) implementation of **NOM** — a governed MCP gateway that sits between AI agents and the tools they use, adding the enterprise controls that MCP itself does not provide.
>
> **nom-py is a Python port of the original NOM implementation, which was written in Go.**

---

## What is this project?

**nom-py** is a Python implementation of NOM, ported from an internal Go codebase. NOM is inspired by the [Envoy proxy](https://www.envoyproxy.io/) but purpose-built for AI agents and the Model Context Protocol (MCP).

When AI agents (such as Claude, Copilot, or Cortex agents) need to use tools, they should not connect directly to every tool server. They connect to one gateway — NOM — which handles authentication, authorization, auditing, and safety guardrails, then forwards the call to the correct upstream tool server.

NOM acts as the single enforcement point for all AI-to-tool traffic.

---

## NOM vs MCP

| | **MCP** | **NOM** |
|---|---|---|
| What it is | A protocol (a message format) | An infrastructure component (a gateway) |
| Purpose | Defines how AI agents communicate with tools | Sits between agents and tools to enforce controls |
| Provides | Message schema (`initialize`, `tools/list`, `tools/call`) | Auth, policy, audit, guardrails, routing |
| Analogy | The road | The toll booth on the road |

NOM speaks MCP on both sides — it presents as an MCP server to agents and behaves as an MCP client toward upstream tools. In between, NOM adds everything MCP omits: identity, authorization, policy filtering, structured audit logging, and safety metadata.

---

## Architecture

### Without NOM

```
[ AI Agent ] <-- MCP --> [ Tool Server 1 ]
[ AI Agent ] <-- MCP --> [ Tool Server 2 ]
[ AI Agent ] <-- MCP --> [ Tool Server 3 ]
```

Problems: separate auth per server, no unified audit, no central policy, no way to block risky tool calls.

### With NOM

```
              [ AI Agent ]
                   |
              speaks MCP
                   ▼
       [ NOM Gateway :8001 ]
    auth → policy → audit → guardrails
                   |
      +------------+------------+
      ▼            ▼            ▼
  [Tool 1]     [Tool 2]     [Tool 3]
  upstream :9001
```

Result: one endpoint, one auth model, one policy engine, one audit log — regardless of how many upstream tool servers exist.

---

## What has been built (Phases 1–5)

### Phase 1 — Scaffold
FastAPI app, `/health` and `/mcp` routes, uvicorn boot, basic request flow.

### Phase 2 — MCP forwarding pipeline
Full `tools/list` and `tools/call` proxying to upstream. nom-py receives a JSON-RPC request, forwards it via `httpx`, returns the upstream response verbatim.

### Phase 3 — Token auth + policy enforcement
Every request passes through three gates before it reaches the upstream:

```
Client → [Auth Gate] → [Identity Gate] → [Policy Gate] → Upstream
```

- **Auth gate** — extracts `Authorization: Bearer <token>` from header, body, or query param. Missing or unknown token → rejected.
- **Identity gate** — looks up token in `config/policy.yaml`, attaches `user_id` + `groups` as a `Principal`.
- **Policy gate** — checks `tools.<name>.allow` and `allowed_groups`. Not allowed → rejected.

`tools/list` is also filtered: users only see tools they are permitted to call. Forbidden tools are invisible, not just blocked.

### Phase 4 — Audit stream + idempotency + revert metadata
Every request emits one structured JSON audit record with per-stage timing:

```
auth.extract → auth.lookup → policy.evaluate → safety.revertible
→ idempotency.miss/hit → upstream.call → dispatch.complete
```

Idempotency: mutating tools replay cached results for duplicate requests (keyed on `request_id`). Revert metadata (`mutating`, `revertible`, `compensating_tool`) is declared per-tool in `policy.yaml` and recorded in every audit event.

### Phase 5 — stdio bridge + Claude Desktop integration
A thin translation shim (`cmd/stdio_bridge/main.py`) lets stdio-only MCP clients (such as Claude Desktop) talk to nom-py's HTTP interface. nom-py itself was not modified — the bridge is 100% transport translation.

The bridge reads JSON-RPC from stdin, POSTs to nom-py with an injected `Authorization: Bearer` token, and writes responses to stdout. All logs go to stderr so Claude's parser is never confused.

---

## Running the project

nom-py requires **two processes** running simultaneously:

### Port 9001 — upstream mock tool server

```powershell
uvicorn cmd.upstream.main:app --reload --port 9001
```

This is a lightweight mock MCP server that exposes three tools: `get_weather`, `list_users`, and `delete_user`. In production this would be a real tool server.

### Port 8001 — nom-py gateway

```powershell
uvicorn app.main:app --reload --port 8001
```

This is the governed gateway. All client traffic goes here. nom-py enforces auth, policy, and audit before forwarding to upstream :9001.

### Quick smoke test (no Claude Desktop needed)

```powershell
.venv\Scripts\Activate.ps1

$env:NOM_URL   = "http://localhost:8001/mcp"
$env:NOM_TOKEN = "tok-alice"

Get-Content cmd\stdio_bridge\test_handshake.txt | python cmd\stdio_bridge\main.py
```

---

## Token identities

Tokens are configured in `config/policy.yaml`:

| Token | User | Groups | Can call |
|---|---|---|---|
| `tok-alice` | alice | developers, analysts | `get_weather`, `list_users` |
| `tok-bob` | bob | analysts | `list_users` only |
| `nom-admin-secret` | (admin) | admin | all permitted tools |
| _(no token)_ | — | — | rejected at auth gate |

---

## Policy configuration (`config/policy.yaml`)

```yaml
tools:
  get_weather:
    allow: true
    allowed_groups: ["developers", "admin"]
    mutating: false

  list_users:
    allow: true
    allowed_groups: ["analysts", "admin"]
    mutating: false

  delete_user:
    allow: false          # globally denied
    reason: "destructive operations not permitted via this gateway"
    mutating: true
    revertible: false
```

Tools with `allow: false` are stripped from `tools/list` responses — clients never learn they exist.

---

## Claude Desktop integration

nom-py ships with a stdio bridge that allows any stdio-only MCP client to connect to the HTTP gateway. Claude Desktop is the reference integration.

### How it works

```
Claude Desktop
    │  spawns process
    ▼
cmd/stdio_bridge/main.py
    │  stdin  → JSON-RPC line
    │  POST http://localhost:8001/mcp  (Authorization: Bearer <token>)
    │  response → stdout
    ▼
nom-py :8001  →  enforce auth + policy + audit  →  upstream :9001
```

### Two MCP connectors — one gateway, two identities

Claude Desktop is configured with **two separate entries** pointing at the same nom-py gateway, each carrying a different token:

```json
{
  "mcpServers": {
    "nom-py-alice": {
      "command": "C:\\...\\python.exe",
      "args": ["C:\\...\\cmd\\stdio_bridge\\main.py"],
      "env": { "NOM_URL": "http://localhost:8001/mcp", "NOM_TOKEN": "tok-alice", ... }
    },
    "nom-py-bob": {
      "command": "C:\\...\\python.exe",
      "args": ["C:\\...\\cmd\\stdio_bridge\\main.py"],
      "env": { "NOM_URL": "http://localhost:8001/mcp", "NOM_TOKEN": "tok-bob", ... }
    }
  }
}
```

**Why two connectors?**

| Connector | Token | What Claude sees |
|---|---|---|
| `nom-py-alice` | `tok-alice` (developers + analysts) | `get_weather` + `list_users` |
| `nom-py-bob` | `tok-bob` (analysts only) | `list_users` only |

This demonstrates identity-aware catalog filtering: same gateway, same upstream, same policy config — but each client receives only the tools their identity is permitted to use. Unauthorized tools are invisible to the client, not merely rejected at call time.

### Writing the config (first time)

Claude Desktop on Windows is an MSIX sandbox app. Its config lives at a path like:

```
%LOCALAPPDATA%\Packages\Claude_<hash>\LocalCache\Roaming\Claude\claude_desktop_config.json
```

Writing to `%APPDATA%\Claude\` is silently ignored. Use the restore script instead — it auto-detects the correct path.

### Restoring the config (when Claude wipes it)

Claude Desktop occasionally resets its `mcpServers` config on update or reinstall. When that happens, run:

```powershell
cd C:\Users\L132478\nom-py
.\scripts\restore_claude_config.ps1
```

The script is **idempotent** — safe to run at any time. It:
- Auto-detects the MSIX sandbox path (adapts if the package hash changes)
- Preserves all existing Claude preferences (only overwrites `mcpServers`)
- Writes BOM-free UTF-8 (Claude silently fails to parse BOM-prefixed files)
- Adds all three servers: `nom-py-alice`, `nom-py-bob`, `incident-responder`

What the script does under the hood:

```powershell
# 1. Auto-detect MSIX path
$claudePkg = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "Claude_*" |
    Select-Object -First 1 -ExpandProperty FullName
$configPath = Join-Path $claudePkg "LocalCache\Roaming\Claude\claude_desktop_config.json"

# 2. Load existing config (preserves preferences), merge mcpServers
$existing = Get-Content $configPath -Raw | ConvertFrom-Json
$existing | Add-Member -MemberType NoteProperty -Name mcpServers -Value $mcpServers -Force

# 3. Write BOM-free UTF-8
[System.IO.File]::WriteAllText($configPath, $outputJson, [System.Text.UTF8Encoding]::new($false))
```

After running → fully restart Claude Desktop (system tray → Quit → relaunch).

---

## Audit log format

Every request produces one JSON line on `nom-py.audit`:

```json
{
  "request_id": "e813c93d-...",
  "user_id": "alice",
  "method": "tools/call",
  "duration_ms": 268.41,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.01, "source": "header", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.03, "token_hint": "tok-al…", "result": "ok" },
    { "stage": "policy.evaluate",   "t_ms": 0.24, "tool": "get_weather", "decision": "allow" },
    { "stage": "safety.revertible", "t_ms": 0.24, "mutating": false },
    { "stage": "upstream.call",     "t_ms": 268.35, "latency_ms": 268.03, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 268.37, "outcome": "ok" }
  ]
}
```

A policy denial short-circuits at `policy.evaluate` — `upstream.call` is absent, and total duration is under 1ms.

---

## Idempotency — proof from audit logs

Mutating tools (`mutating: true` in `policy.yaml`) are deduplicated: the same call with the same arguments only reaches the upstream once. Subsequent identical calls return the cached result.

The idempotency key is `SHA-256(user_id + tool_name + args)[:32]`. Same inputs always produce the same key regardless of `request_id`.

### How it was tested

`delete_user` is globally denied by default. To test idempotency, `allow: true` was temporarily set in `config/policy.yaml`. The same call was sent three times.

---

### Call 1 — `idempotency.miss` (upstream executed, result cached)

```json
{
  "request_id": "be7d14ce-323c-4ade-8dc3-c5d36712ba68",
  "user_id": "alice",
  "method": "tools/call",
  "duration_ms": 262.14,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.02, "source": "body",   "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.04, "token_hint": "tok-al…", "result": "ok" },
    { "stage": "policy.evaluate",   "t_ms": 0.35, "tool": "delete_user", "decision": "allow" },
    { "stage": "safety.revertible", "t_ms": 0.36, "mutating": true, "revertible": false },
    { "stage": "idempotency.miss",  "t_ms": 0.77, "key": "2f54dd9e53f3d464eb193c631d527bbb" },
    { "stage": "upstream.call",     "t_ms": 262.12, "latency_ms": 261.3, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 262.14, "outcome": "ok" }
  ]
}
```

`idempotency.miss` → key not in cache → upstream called (262ms) → result stored under key `2f54dd9e…`.

---

### Calls 2 & 3 — `idempotency.hit` (upstream NOT called, cached result returned)

```json
{
  "request_id": "be840984-a68e-487b-a863-7fa2bffedaf6",
  "user_id": "alice",
  "duration_ms": 0.39,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.02 },
    { "stage": "auth.lookup",       "t_ms": 0.04, "result": "ok" },
    { "stage": "policy.evaluate",   "t_ms": 0.26, "decision": "allow" },
    { "stage": "safety.revertible", "t_ms": 0.26, "mutating": true },
    { "stage": "idempotency.hit",   "t_ms": 0.39, "key": "2f54dd9e53f3d464eb193c631d527bbb" },
    { "stage": "dispatch.complete", "t_ms": 0.39, "outcome": "ok" }
  ]
}
```

`idempotency.hit` → key found in cache → pipeline exited before `upstream.call`. `upstream.call` is **absent** from the audit. `duration_ms: 0.39ms` vs 262ms for the miss.

---

### Miss vs hit — side by side

| | Call 1 — miss | Call 2 — hit | Call 3 — hit |
|---|---|---|---|
| `duration_ms` | **262.14ms** | **0.39ms** | **0.69ms** |
| `upstream.call` present | ✅ yes (261ms) | ❌ no | ❌ no |
| `idempotency` event | `miss` | `hit` | `hit` |
| Idempotency key | `2f54dd9e…` | `2f54dd9e…` (same) | `2f54dd9e…` (same) |
| Upstream actually called | yes | **no** | **no** |

The upstream received exactly **one** `delete_user` call. Calls 2 and 3 were served entirely from the nom-py cache — the side effect was not repeated.

---

### Read-only tools bypass idempotency entirely

Sending `get_weather` twice:

```json
{ "stage": "safety.revertible", "mutating": false, "revertible": false }
```

No `idempotency.miss` or `idempotency.hit` event appears. `upstream.call` is present on both calls — read-only tools always hit the upstream. The `mutating: false` flag in `safety.revertible` is the gate that skips the idempotency block entirely.

---

## Project structure

```
app/
  main.py              # FastAPI entrypoint (:8001)
  config.py            # Loads policy.yaml
  api/routes/
    health.py          # GET /health
    mcp.py             # POST /mcp  (main entry point)
  auth/
    token_auth.py      # Token extraction + lookup
    models.py          # Principal dataclass
  mcp/
    dispatcher.py      # Request orchestration (auth → policy → audit → upstream)
    protocol.py        # JSON-RPC types
    registry.py        # Upstream server registry
    upstream.py        # httpx forwarding client
    adapters/          # Pluggable upstream adapters
  policy/
    engine.py          # Tool allow/deny + tools/list filtering
    errors.py          # Policy error types
  observability/
    audit.py           # Structured audit emission
    context.py         # Per-request trace context
  safety/
    idempotency.py     # Mutating-tool deduplication

cmd/
  upstream/main.py     # Mock tool server (:9001)
  stdio_bridge/main.py # Claude Desktop ↔ nom-py bridge
  client/main.py       # CLI test client

config/
  policy.yaml          # Tokens, groups, tool permissions, upstream endpoint

docs/
  phase1_architecture_understanding.md
  phase2_mcp_core_flow.md
  phase3_auth_and_policy.md
  phase4_governance_observability.md
  phase5_guardrails.md
```

---

## Dependencies

```
fastapi        # Web framework
uvicorn        # ASGI server
httpx          # Async HTTP client (upstream forwarding)
pyyaml         # Policy config loading
pydantic       # Request/response validation
python-dotenv  # Environment variable loading
pytest         # Test runner
```

---

## What is NOT yet implemented

- **GitHub OAuth / OBO auth** — token auth is static config-based (Phase 6+)
- **Concurrent-request safety at real scale** — not load-tested
- **Multi-tenant isolation beyond token-mapped groups**
- **Compatibility with MCP clients other than Claude Desktop**
- **Production TLS / secrets management**
