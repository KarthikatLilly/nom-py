# Phase 2 — MCP Core Flow

## Goal
Build `/mcp` endpoint with initialize, tools/list, tools/call.

## Design
- one virtual MCP surface
- upstream adapters (HTTP + stdio)
- registry from YAML

## Endpoints
- POST /mcp
- GET /health

## Tool naming rule
`<namespace>__<tool_name>`

## Adapters
- HTTP MCP adapter
- stdio MCP adapter (npx / uvx)

## Deliverable
- working /mcp with mock upstream
- namespaced tools/list
- dispatched tools/call