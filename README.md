# nom-py

> A Python (FastAPI) implementation of **NOM** — a governed MCP gateway that sits between AI agents and the tools they use, adding the enterprise controls that MCP itself does not provide.
>
> **nom-py is a Python port of the original NOM implementation, which was written in Go.**

---

## What is this project?

**nom-py** is a Python implementation of NOM, ported from an internal Go codebase. NOM is inspired by the [Envoy proxy](https://www.envoyproxy.io/) but purpose-built for AI agents and the Model Context Protocol (MCP).

When AI agents (such as Claude, Copilot, or Cortex agents) need to use tools, they should not connect directly to every tool server. They connect to one gateway — NOM — which handles authentication, authorization, auditing, and safety guardrails, then forwards the call to the correct upstream tool server.

NOM acts as the single enforcement point for all AI-to-tool traffic: authentication, policy evaluation, audit logging, and routing.

---

## NOM vs MCP

NOM and MCP are not the same thing.

| | **MCP** | **NOM** |
|---|---|---|
| What it is | A protocol (a message format) | An infrastructure component (a gateway) |
| Purpose | Defines how AI agents communicate with tools | Sits between agents and tools to enforce controls |
| Provides | Message schema (`initialize`, `tools/list`, `tools/call`) | Auth, policy, audit, guardrails, routing |
| Analogy | The road | The toll booth on the road |

- **MCP** defines how agents and tools speak to each other.
- **NOM** governs and mediates that conversation.

NOM speaks MCP on both sides:
- Toward the agent — it presents as an MCP server.
- Toward upstream tools — it behaves as an MCP client.

In between, NOM adds everything MCP omits: authentication, authorization, policy enforcement, audit logging, rate limiting, guardrails on destructive actions, upstream routing, idempotency, and observability.

---

## Architecture

### Without NOM

```
[ AI Agent ] <-- MCP --> [ Tool Server 1 ]
[ AI Agent ] <-- MCP --> [ Tool Server 2 ]
[ AI Agent ] <-- MCP --> [ Tool Server 3 ]
```

Problems: separate auth per server, no unified audit, no central policy, no way to block risky tool calls, fragmented tool discovery.

### With NOM

```
           [ AI Agent ]
                |
           speaks MCP
                v
    [ NOM Gateway (also speaks MCP) ]
    auth -> policy -> audit -> guardrails
                |
     +----------+----------+
     v          v          v
 [Tool 1]   [Tool 2]   [Tool 3]
```

Result: one endpoint, one auth model, one policy engine, one audit log, one place to evaluate and potentially block tool calls.

---

## Envoy Inspiration

Envoy is a general-purpose Layer 7 proxy that adds routing, load balancing, TLS termination, and observability between services. NOM borrows Envoy's core ideas:

- **Filter chain** — every request passes through: auth → policy → audit → route
- **Upstream routing** — determines which tool server handles the call
- **Observability** — structured logs, metrics, and traces on every decision

The key difference: Envoy is a generic HTTP gateway. NOM is an MCP-aware gateway designed specifically for AI agent traffic.

---

## Why FastAPI?

The original NOM uses Go's `net/http`. This Python port uses FastAPI for the following reasons:

| Framework | Assessment |
|---|---|
| Flask | Synchronous, no native async support |
| Django | Overly heavy for a proxy workload |
| Starlette | Low-level, less ergonomic |
| **FastAPI** | Async-native, JSON-first, strong typing, middleware support |

FastAPI is well-suited to NOM's requirements:
- MCP uses JSON-RPC over HTTP — FastAPI handles JSON natively.
- NOM proxies to upstream MCP servers — requires async HTTP (`httpx`).
- NOM has a middleware chain (auth → policy → audit) — maps directly to FastAPI middleware.
- FastAPI generates interactive Swagger docs automatically at `/docs`.

---

## Project Scope

This is a prototype intended to validate the architecture. It is not production-ready.

**In scope:**
- Single `/mcp` endpoint implementing MCP JSON-RPC
- YAML-defined registry of upstream MCP servers
- Auth layer (GitHub OAuth, provider-abstracted)
- Policy engine (YAML rules: allow / deny / approval-required)
- Audit log for every tool call decision
- Idempotency keys for mutating operations
- Revert/compensation metadata for reversible actions
- Guardrails against destructive or high-risk tool calls

**Out of scope (for now):**
- Production-grade performance tuning
- Full enterprise on-behalf-of (OBO) auth
- Complete MCP specification coverage
- Dynamic service discovery
- SSE / advanced streaming
- High availability / horizontal scaling

---

## Getting Started

### 1. Setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Run the server

```bash
uvicorn app.main:app --reload --port 8001
```

### 3. Test the endpoints

**Health check:**

```powershell
curl http://localhost:8001/health
# Expected: {"status":"ok","service":"nom-py"}
```

**MCP handshake (PowerShell):**

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8001/mcp" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"jsonrpc":"2.0","id":1,"method":"initialize"}'
```

Expected response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": { "tools": { "listChanged": false } },
    "serverInfo": { "name": "nom-py", "version": "0.1.0" }
  }
}
```

This is the standard MCP server handshake: the gateway identifies its protocol version, capabilities, and server identity.

### 4. Interactive docs

Open [http://localhost:8001/docs](http://localhost:8001/docs) for the auto-generated Swagger UI.

---

## Repository Layout

```
nom-py/
├── app/
│   ├── main.py                # FastAPI app entry point
│   ├── config.py              # App configuration
│   ├── api/routes/            # HTTP routes (/health, /mcp)
│   ├── mcp/                   # MCP dispatcher, registry, upstream adapters
│   ├── auth/                  # Authentication (GitHub OAuth)
│   ├── policy/                # YAML-driven policy engine
│   ├── observability/         # Audit logging and structured observability
│   ├── safety/                # Idempotency and compensating actions
│   └── models/                # Data models
├── config/
│   ├── servers.yaml           # Upstream MCP server registry
│   ├── policy.yaml            # RBAC and approval rules
│   └── aws.yaml               # AWS-specific guardrail configuration
├── docs/                      # Phase-by-phase architecture notes
├── tests/
├── requirements.txt
└── README.md
```

---

## Roadmap

| Phase | Focus | Deliverable |
|---|---|---|
| 1 | Architecture understanding | Map Go NOM concepts to Python equivalents |
| 2 | MCP core flow | Working `/mcp` with `initialize`, `tools/list`, `tools/call` |
| 3 | Auth and policy | GitHub OAuth + YAML policy engine |
| 4 | Audit, idempotency, revert | Full decision trail and compensating actions |
| 5 | Guardrails and demo | End-to-end demo with real tool scenarios |

Each phase has a corresponding document in `docs/`.

---

## Summary

**nom-py is a governed MCP broker, ported from Go to Python, that exposes a single safe tool surface to AI agents and treats every tool call as an auditable, policy-evaluated, and potentially reversible operation.**

---

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io)
- [Envoy Proxy Architecture](https://www.envoyproxy.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com)