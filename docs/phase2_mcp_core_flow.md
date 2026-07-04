# Phase 2 — MCP Core Flow ✅

## Goal
Make nom-py a working policy-less MCP proxy that forwards MCP JSON-RPC traffic
from a client to a single upstream MCP server.

## What was built
- `MCPDispatcher` handling `initialize`, `tools/list`, `tools/call`
- `UpstreamClient` forwarding messages via httpx
- Refactored `/mcp` route delegating to dispatcher
- Dummy upstream server exposing 3 tools
- Dummy client for end-to-end testing
- `config/policy.yaml` with structure matching Go NOM

## Verified
- `initialize` returns nom-py identity + upstream capabilities
- `tools/list` returns 3 tools from upstream
- `tools/call` executes tools and returns results
- All three tools work: get_weather, list_users, delete_user

## Not yet enforced
- Token auth
- Policy allow/deny
- GitHub OAuth

## Design decisions
- Path A: POST `/mcp` only (no SSE yet) — matches Go conceptually
- Single upstream endpoint (matches Go's 1:1 proxy design)
- Single `policy.yaml` (matches Go structure)
- Kept dummy upstream + client mirroring Go's `cmd/` structure

## Next
Phase 3 will add:
- Static token validation
- Policy-based tool allow/deny
- Optional GitHub OAuth