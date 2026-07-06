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

# Phase 3 — Auth + Policy ✅

## Goal

nom-py becomes a real gatekeeper. It validates identity and enforces per-tool
allow/deny rules before forwarding to the upstream.

---

## 🎯 What Phase 3 achieves

> nom-py should **stop unauthorized users** and **block dangerous tools** — even if the upstream would happily execute them.

| Behavior | Before (Phase 2) | After (Phase 3) |
|---|---|---|
| Request with no token | ✅ Succeeds | ❌ Rejected — auth error |
| Wrong token | ✅ Succeeds | ❌ Rejected — auth error |
| `tok-alice` calling `get_weather` | ✅ Succeeds | ✅ Succeeds (developers group allowed) |
| `tok-bob` calling `get_weather` | ✅ Succeeds | ❌ Rejected (not in developers) |
| Anyone calling `delete_user` | ✅ Succeeds | ❌ Rejected (globally denied) |
| `tools/list` | Shows all 3 tools | Shows only tools user can access |

---

## 🧠 The mental model

Every request now goes through **3 gates** before nom-py forwards it:

```
Client → [1. Auth Gate] → [2. Identity Gate] → [3. Policy Gate] → Upstream
```

**Gate 1 — Auth:** Do you have a valid token?
→ Extract from `Authorization: Bearer ...` header, body, or query param.
→ Missing or unknown → **reject**.

**Gate 2 — Identity:** Who are you and what groups do you belong to?
→ Look up token in `policy.yaml`.
→ Attach `user_id` + `groups` to the request as a `Principal`.

**Gate 3 — Policy:** Are you allowed to use this specific tool?
→ Check `tools.<tool_name>.allow` and `allowed_groups`.
→ Not allowed → **reject**.

Only if all three gates pass does nom-py forward to the upstream.

---

## 📁 Files built

### New files

| File | Purpose |
|---|---|
| `app/auth/models.py` | `Principal` dataclass — holds `user_id`, `groups`, `token` |
| `app/auth/token_auth.py` | Extracts + validates tokens, raises `AuthError`, returns `Principal` |
| `app/policy/engine.py` | `PolicyEngine` — evaluates tool calls against `policy.yaml` rules |
| `app/policy/errors.py` | `PolicyDenied` exception (`code=-32003`) |

### Modified files

| File | Change |
|---|---|
| `config/policy.yaml` | Real tokens + tool rules filled in |
| `app/config.py` | Exposes `auth_enabled`, `tokens`, `tool_rules` |
| `app/mcp/dispatcher.py` | Enforces auth + policy before forwarding |
| `app/api/routes/mcp.py` | Extracts token from request, passes `Principal` to dispatcher |
| `cmd/client/main.py` | Expanded to test 4 scenarios (no token, alice, bob, invalid) |

---

## 🔑 What is a bearer token?

A **bearer token** is a string that means *"whoever holds this = whoever this belongs to."*
No password, no signature — presenting the token proves identity.

```
Authorization: Bearer tok-alice
```

It literally means *"the bearer of this token."* Like a movie ticket — whoever holds it gets in.

nom-py accepts tokens from **3 places** (checked in order):

```
1. Authorization: Bearer tok-alice    ← preferred (HTTP header)
2. body: {"token": "tok-alice"}       ← for Swagger convenience
3. ?token=tok-alice                   ← easiest for browser testing
```

**Code:** `app/auth/token_auth.py` → `extract_token()`

```python
# 1. Authorization header
auth_header = request.headers.get("authorization", "")
if auth_header.lower().startswith("bearer "):
    return auth_header[7:].strip()

# 2. JSON body
if isinstance(body, dict) and "token" in body:
    return str(body["token"])

# 3. Query param
if "token" in request.query_params:
    return request.query_params["token"]
```

---

## 👥 Users — where they're defined

All users and permissions live in **`config/policy.yaml`** — nothing is hardcoded in Python:

```yaml
auth:
  enabled: true
  admin_token: "nom-admin-secret"
  tokens:
    "tok-alice":
      user_id: "alice"
      groups: ["developers", "analysts"]
    "tok-bob":
      user_id: "bob"
      groups: ["analysts"]

tools:
  get_weather:
    allow: true
    allowed_groups: ["developers"]
  list_users:
    allow: true
    allowed_groups: ["analysts"]
  delete_user:
    allow: false
    reason: "destructive operations not permitted via this gateway"
  admin_reset:
    allow: false
    reason: "admin tools restricted to internal services only"
```

| Token | User | Groups | Can access |
|---|---|---|---|
| `tok-alice` | alice | developers + analysts | `get_weather` + `list_users` |
| `tok-bob` | bob | analysts only | `list_users` only |
| `nom-admin-secret` | (reserved) | — | Invalid token for now — not in `tokens:` block |

Changing users = editing YAML. No code change needed.

---

## 🔍 How authentication works — step by step

When a request hits `POST /mcp`:

**Step 1 — Route extracts token**
`app/api/routes/mcp.py` → calls `authenticate(request, payload)`

`initialize` is skipped — the MCP handshake must succeed before the client can authenticate. An anonymous `Principal` is used for that method only.

**Step 2 — Token extraction**
`app/auth/token_auth.py` → `extract_token()` tries header → body → query param.

**Step 3 — Lookup in policy.yaml**
`app/auth/token_auth.py` → `authenticate()`

```python
token_info = settings.tokens.get(token)   # dict from policy.yaml
if not token:
    raise AuthError("Missing token", code=-32001)
if not token_info:
    raise AuthError("Invalid token", code=-32001)
```

**Step 4 — Build Principal**
`app/auth/models.py`

```python
Principal(user_id="alice", groups=["developers", "analysts"], token="tok-alice")
```

**Step 5 — Policy evaluation**
`app/policy/engine.py` → `evaluate_tool_call(principal, tool_name)`

```python
rule = self.rules.get(tool_name)
if rule is None:                        # unknown tool → deny (least privilege)
    raise PolicyDenied(...)
if not rule.get("allow", False):        # globally denied tool
    raise PolicyDenied(...)
if allowed_groups and not principal.in_any_group(allowed_groups):
    raise PolicyDenied(...)             # wrong group
```

**Full path:**

```
Client sends "Bearer tok-alice"
        ↓
    app/api/routes/mcp.py
        ↓
authenticate() → extract_token() → settings.tokens.get(token)
        ↓
Principal(user_id="alice", groups=["developers", "analysts"])
        ↓
MCPDispatcher.handle(msg, principal)
        ↓
PolicyEngine.evaluate_tool_call(principal, "delete_user")
        ↓
rule says allow=false → PolicyDenied raised
        ↓
JSON-RPC error -32003 returned to client
```

---

## 🧪 Test output — 4 scenarios

Run: `python cmd/client/main.py`

### Scenario 1 — NO TOKEN

```
initialize   → ✅  { "serverInfo": { "name": "nom-py", "version": "0.3.0" } }
tools/list   → ❌  { "code": -32001, "message": "Missing token" }
get_weather  → ❌  { "code": -32001, "message": "Missing token" }
list_users   → ❌  { "code": -32001, "message": "Missing token" }
delete_user  → ❌  { "code": -32001, "message": "Missing token" }
```

### Scenario 2 — ALICE (developers + analysts)

```
initialize   → ✅  { "serverInfo": { "name": "nom-py", "version": "0.3.0" } }
tools/list   → ✅  shows get_weather + list_users only (delete_user hidden)
get_weather  → ✅  "Weather in Hyderabad: 72°F, sunny."
list_users   → ✅  "Users: alice, bob, charlie"
delete_user  → ❌  { "code": -32003, "message": "Tool 'delete_user' denied: destructive operations not permitted via this gateway" }
```

### Scenario 3 — BOB (analysts only)

```
initialize   → ✅  { "serverInfo": { "name": "nom-py", "version": "0.3.0" } }
tools/list   → ✅  shows list_users only (get_weather + delete_user hidden)
get_weather  → ❌  { "code": -32003, "message": "Tool 'get_weather' requires one of groups: ['developers']" }
list_users   → ✅  "Users: alice, bob, charlie"
delete_user  → ❌  { "code": -32003, "message": "Tool 'delete_user' denied: destructive operations not permitted via this gateway" }
```

### Scenario 4 — INVALID TOKEN (`tok-nobody`)

```
initialize   → ✅  { "serverInfo": { "name": "nom-py", "version": "0.3.0" } }
tools/list   → ❌  { "code": -32001, "message": "Invalid token" }
get_weather  → ❌  { "code": -32001, "message": "Invalid token" }
list_users   → ❌  { "code": -32001, "message": "Invalid token" }
delete_user  → ❌  { "code": -32001, "message": "Invalid token" }
```

---

## 🔥 The moment nom-py becomes real

When you see `delete_user` finally get denied — that's nom-py stopping being infrastructure code and becoming a real **gatekeeper**. That single denial message is the whole point of the project.

---

## ⚠️ Security caveats (prototype honesty)

| Issue | Reality | Fix it now? |
|---|---|---|
| Tokens stored in plaintext YAML | Real systems use hashed tokens + secrets manager | ❌ No — prototype |
| No token expiry | Real tokens rotate every hour/day | ❌ No — prototype |
| No brute-force protection | Someone could try 1M tokens against `/mcp` | ❌ No — prototype |
| No HTTPS | Tokens travel in plaintext over the wire | ❌ No — local dev only |
| No token revocation | Once in YAML, it works forever | ❌ No — prototype |
| Tokens are static strings | Real systems use JWTs with signatures | ❌ No — Phase 3 intent |

If asked *"Is this production-ready?"*:

> "No — it's a policy-enforcement prototype. Tokens are static strings in YAML instead of JWTs, and there's no HTTPS or revocation. But the enforcement model — extract identity → evaluate policy → allow or deny — is exactly what a production version would do. Swapping bearer tokens for JWTs is a Phase 5+ upgrade, not an architecture change."

---

## 🧠 Key design decisions

**Least privilege by default** (`app/policy/engine.py`)
```python
if rule is None:
    raise PolicyDenied(...)   # unknown tools → denied, not allowed
```
New tool added to upstream without a YAML rule → blocked automatically.

**`tools/list` filtering** — Alice sees only `get_weather` + `list_users`. Bob sees only `list_users`. If the AI agent can't *see* a tool, it won't try to call it in the first place.

**`initialize` is auth-exempt** (`app/api/routes/mcp.py`) — The MCP handshake must succeed before the client knows about auth. An anonymous `Principal` is used only for that call.

**JSON-RPC error codes:**
- `-32001` → auth error (missing/invalid token)
- `-32003` → policy error (denied by rule or group)
- `-32601` → method not supported

**Distinct error messages** — `"Missing token"` vs `"Invalid token"` vs `"Tool X denied"` vs `"Tool X requires groups [Y]"` — different errors help clients and humans understand exactly what went wrong.

---

## 🧪 Quick Swagger tests

Open `http://localhost:8001/docs` → `POST /mcp`

**Test A — Wrong group (expect denied)**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"get_weather","arguments":{"location":"Delhi"}},
 "token":"tok-bob"}
```
Expected: `-32003` — Bob isn't in `developers`.

**Test B — Admin token (expect invalid)**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","token":"nom-admin-secret"}
```
Expected: `-32001` — `admin_token` is a separate YAML key, not in the `tokens:` block. Design gap to address in Phase 4.

**Test C — Unknown tool (expect least-privilege deny)**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"nonexistent_tool","arguments":{}},
 "token":"tok-alice"}
```
Expected: `-32003` — no policy rule → denied.

---

## Not yet added

- GitHub OAuth OBO flow (deferred)
- Audit logging (Phase 4)
- Idempotency (Phase 4)
- Compensation / revert (Phase 4)

---

## 🚀 What's next — Phase 4

| Missing capability | Fixed by |
|---|---|
| No audit trail of who did what | Phase 4 |
| No idempotency on mutating calls | Phase 4 |
| No compensation / revert design | Phase 4 |
| No approval flow for high-risk actions | Phase 5 |
| No stdio bridge for Claude Desktop | Phase 5 |
| GitHub OAuth still disabled | Optional Phase 5 |

Phase 4 is the **governance + memory** layer:
- Every tool call gets logged (who, when, what, decision, latency)
- Idempotency keys prevent double-execution
- Revert metadata for compensating actions
- Foundation for approvals

That's the most conceptually interesting phase — it's where nom-py gains memory of what it did and the ability to undo it.