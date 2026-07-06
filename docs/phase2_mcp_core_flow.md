<style>
a {
    text-decoration: none;
    color: #464feb;
}
tr th, tr td {
    border: 1px solid #e6e6e6;
}
tr th {
    background-color: #f5f5f5;
}
</style>

# Phase 2 — MCP Core Flow ✅

## Goal

Make nom-py a working (policy-less) MCP proxy that forwards MCP JSON-RPC
traffic from a client to a single upstream MCP server.

## What was actually built

### New files
| File | Purpose |
|---|---|
| `app/config.py` | Loads `policy.yaml` and exposes `settings.upstream_endpoint`. Prevents hardcoded config. |
| `app/mcp/dispatcher.py` | The brain of nom-py. Routes MCP methods (`initialize`, `tools/list`, `tools/call`) and delegates forwarding. |
| `app/mcp/upstream.py` | The forwarder. Uses `httpx.AsyncClient` to POST JSON-RPC messages to the upstream MCP server. |
| `cmd/upstream/main.py` | A dummy MCP server (FastAPI, port 9001) with 3 fake tools. Mirrors Go NOM's `cmd/upstream/main.go`. |
| `cmd/client/main.py` | A dummy MCP client that hits nom-py end-to-end. Mirrors Go NOM's `cmd/client/main.go`. |

### Modified files

| File | Change |
|---|---|
| `app/api/routes/mcp.py` | Refactored to delegate to `MCPDispatcher`. Route is now thin. |
| `config/policy.yaml` | Added upstream endpoint block. Placeholder sections for auth/tokens/tools ready for Phase 3. |

### `cmd/upstream/main.py` — the fake MCP backend

- It's a **standalone FastAPI app** running on port 9001.
- It has **nothing to do with nom-py** — it's a separate process.
- It pretends to be a real upstream MCP server exposing 3 tools:
  - `get_weather`
  - `list_users`
  - `delete_user`
- It responds to MCP JSON-RPC requests exactly like a real MCP server would.

Without it, nom-py would have nothing to forward to. This fake upstream lets you verify nom-py's forwarding logic in isolation. Think of it like this: nom-py is the toll booth. The fake upstream is the road behind it. You built both so you could drive through the whole system.

### `cmd/client/main.py` — the fake MCP client

- It's a **standalone Python script** (not a server).
- It uses `httpx` to hit nom-py at `http://localhost:8001/mcp`.
- It sends the same JSON-RPC messages Claude Desktop would send.
- It prints out what nom-py returns.

Because Claude Desktop can't see nom-py yet (HTTP, not stdio), the dummy client acts as a test agent hitting your gateway. Think of this as your **"pretend Claude"** for now.

## What we actually built — in categories

- **nom-py** is now an **MCP gateway/proxy** (speaks MCP on both sides).
- **cmd/upstream** is a real MCP server (same category as `incident-responder`).
- **cmd/client** is a real MCP client (simpler version of Claude Desktop).
- We did NOT build a "connector" — connectors are Anthropic's marketing term for
  MCP integrations in Claude Desktop's directory.

## Did we make an MCP server? A connector? A gateway? What actually is this?

Great question. Let me draw the line clearly.

### What exists in the MCP world

| Thing | What it is | Example |
|---|---|---|
| **MCP server** | Speaks MCP, exposes tools | Your `incident-responder` |
| **MCP client** | Consumes MCP tools | Claude Desktop, Copilot |
| **MCP gateway/proxy** | Speaks MCP on both sides, sits in the middle | **nom-py**, Go NOM |
| **Connector** | Anthropic's marketing term for MCP integrations in Claude Desktop | Anthropic Partners |

### So what did you build in Phase 2?

You built:

> **nom-py: an MCP gateway.**
>
> It behaves like an **MCP server** to the client (dummy client), and like an **MCP client** to the upstream (dummy upstream).

That's it. No connector, no new protocol, no LLM. Just a gatekeeper server.

The dummy upstream you built (`cmd/upstream/main.py`) is a **real MCP server** — same category as your `incident-responder`.

The dummy client (`cmd/client/main.py`) is a **real MCP client** — same category as Claude Desktop, just simpler.

## 🖼️ The whole picture

Here's what runs when you test:

```
Terminal 3                  Terminal 2                 Terminal 1
━━━━━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━━━━━
python cmd/client/         uvicorn app.main:app     uvicorn cmd.upstream.main:app
main.py                    --port 8001              --port 9001
━━━━━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━━━━━
      │                          │                          │
      │  POST /mcp               │                          │
      │  {method: tools/list}    │                          │
      ├─────────────────────────▶│                          │
      │                          │                          │
      │                          │  POST /mcp               │
      │                          │  {method: tools/list}    │
      │                          ├─────────────────────────▶│
      │                          │                          │
      │                          │  200 OK                  │
      │                          │  {result: [tools...]}    │
      │                          │◀─────────────────────────┤
      │                          │                          │
      │  200 OK                  │                          │
      │  {result: [tools...]}    │                          │
      │◀─────────────────────────┤                          │
      │                          │                          │
```

Three processes, three ports, three roles.

## Architecture proven

```
[cmd/client]  --MCP-->  [nom-py :8001]  --MCP-->  [cmd/upstream :9001]
```

Three separate processes, JSON-RPC over HTTP end-to-end.

## Verified behaviors

- ✅ `initialize` → nom-py rewrites `serverInfo` to identify itself
- ✅ `tools/list` → transparently forwards 3 tools from upstream
- ✅ `tools/call: get_weather` → executed and returned real content
- ✅ `tools/call: list_users` → executed and returned real content
- ⚠️ `tools/call: delete_user` → **executed successfully with no auth or policy check**
  - This is intentional for Phase 2 — proves the pipe works
  - Phase 3 must block this via policy enforcement

## How to test manually

| | URL |
|---|---|
| Health check | `http://localhost:8001/health` |
| nom-py Swagger | `http://localhost:8001/docs` |
| Upstream Swagger | `http://localhost:9001/docs` |

### PowerShell — single call

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8001/mcp" `
  -Method POST -ContentType "application/json" `
  -Body '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### End-to-end — all 5 calls

```
python cmd/client/main.py
```

```
--- 1. initialize ---
{ "serverInfo": { "name": "nom-py", "version": "0.2.0" } }

--- 2. tools/list ---
{ "tools": ["get_weather", "list_users", "delete_user"] }

--- 3. tools/call: get_weather ---
{ "text": "Weather in Hyderabad: 72\u00b0F, sunny." }

--- 4. tools/call: list_users ---
{ "text": "Users: alice, bob, charlie" }

--- 5. tools/call: delete_user ---     ⚠️ no auth check yet
{ "text": "User alice deleted." }
```

### About the tool responses

All 3 tools return **hardcoded fake data** — intentional. The upstream exists
to test nom-py's forwarding logic, not to implement real business logic.
When nom-py runs against a real MCP server, only the backend changes.

## Claude Desktop integration

Not connected yet. Claude Desktop supports:
- stdio MCP servers (like `incident-responder`) — nom-py is HTTP, not stdio
- Anthropic Connectors directory — nom-py isn't published there

Future options: build a stdio wrapper, or add SSE support in Phase 5.

## Not yet enforced

- Token auth
- Policy allow/deny
- GitHub OAuth

## Design decisions

- **Path A**: POST `/mcp` only, no SSE — matches Go conceptually with 1/3 the code
- **Single upstream endpoint** — matches Go's 1:1 proxy design
- **Single `policy.yaml`** — matches Go structure
- **cmd/ folder** — mirrors Go's `cmd/upstream/` and `cmd/client/`

## Next

Phase 3 will add:
- Static token validation (Bearer / body / query)
- User + group extraction from tokens
- Policy engine reading `policy.yaml`
- Per-tool allow/deny enforcement (`delete_user` will be blocked)
- Optional GitHub OAuth

## 🎯 Summary — quick mental cheat sheet

- **You built:** an MCP gateway (nom-py) + a fake MCP server + a fake MCP client.
- **You did NOT build:** a connector, an LLM, a Claude plugin, or a new protocol.
- **To test:** use `http://localhost:8001/docs` OR `python cmd/client/main.py`.
- **Claude Desktop:** can't see nom-py yet (nom-py is HTTP, not stdio). Not important for the prototype.
- **`cmd/upstream`** = fake backend. **`cmd/client`** = fake agent. Both are for testing.