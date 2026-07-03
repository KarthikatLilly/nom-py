# Day 1 Architecture Note: NOM (Go)

## 1. Entrypoint
- File:
- Server startup:
- Port:

## 2. Route wiring
- /mcp handler:
- /connect handler:
- /register handler:
- Auth routes:

## 3. Auth
- File:
- Provider (GitHub OAuth):
- Callback:
- Session store:

## 4. Policy
- File(s): policy.yaml, aws.yaml
- Loaded by:
- Applied at:

## 5. MCP dispatch
- initialize:
- tools/list:
- tools/call:
- Upstream selection:

## 6. Logging / audit
- Package:
- Fields logged:

## 7. Python mapping
| Go component | Python equivalent |
|---|---|
| main.go | app/main.py |
| routes | app/api/routes/ |
| auth | app/auth/ |
| policy | app/policy/ |
| mcp dispatch | app/mcp/ |
| logging | app/observability/ |