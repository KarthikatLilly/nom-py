# Phase 1 — Architecture Understanding

## Goal
Understand the Go NOM architecture and map each component to a Python equivalent.

## 1. Go repo entrypoint
- main.go:
- port:
- routes registered:

## 2. Core components
- auth (oauth.go, store.go):
- policy (policy.yaml, aws.yaml):
- mcp dispatch:
- logging / audit:

## 3. Envoy-inspired concepts used
- filter chain:
- upstream routing:
- observability:

## 4. Python architecture plan
| Go component | Python equivalent |
|---|---|
| main.go | app/main.py |
| routes | app/api/routes/ |
| auth | app/auth/ |
| policy | app/policy/ |
| mcp dispatch | app/mcp/ |
| logging | app/observability/ |

## 5. Open questions
-
-