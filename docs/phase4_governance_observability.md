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

# Phase 4 — Governance & Observability ✅

## Goal

Make nom-py's internals visible. Every request now emits one structured audit record
that traces every stage it passed through — with per-stage timing, decisions, and outcomes.
Plus: idempotency for mutating tools and revert metadata groundwork.

---

## 🎯 What Phase 4 achieves

| Capability | Before (Phase 3) | After (Phase 4) |
|---|---|---|
| Request traceability | Black box | One audit JSON line per request |
| Per-stage timing | None | `t_ms` on every event |
| Policy decision evidence | Console INFO lines only | Structured event in audit record |
| Upstream latency visibility | None | `latency_ms` in `upstream.call` event |
| Duplicate mutating calls | Re-executed every time | Cached result returned (idempotency) |
| Token in logs | Could appear in full | First 6 chars only (`tok-al…`) |
| Admin token | Dead config key | First-class `Principal(groups=["admin"])` |
| Revert capability metadata | Implicit | Declared per-tool in `policy.yaml` |

---

## 🧠 The mental model

### Before Phase 4 — black box
```
Request in → [magic] → Response out
```
You saw the outcome. No trace of what happened inside.

### After Phase 4 — flight recorder
```
Request in
  ↓ ctx.record("auth.extract")
  ↓ ctx.record("auth.lookup")
  ↓ ctx.record("policy.evaluate")
  ↓ ctx.record("safety.revertible")
  ↓ ctx.record("idempotency.miss/hit")   ← mutating tools only
  ↓ ctx.record("upstream.call")          ← skipped on idempotency.hit
  ↓ ctx.record("dispatch.complete")
  ↓ audit.emit(ctx)  ← ONE JSON line with the full trace
Response out
```

`RequestContext` (ctx) is a dataclass passed by reference through every pipeline stage.
Each stage appends its event as it runs — not summarized at the end.
`audit.emit(ctx)` is a **passive sink**: it reads `ctx.events` and writes one log line.
It never inspects logic. Adding Splunk/DB tomorrow = one new sink, no gate code changes.

---

## 📁 Files built

### New files

| File | Purpose |
|---|---|
| `app/observability/context.py` | `RequestContext` — the flight-recorder dataclass threaded through every stage |
| `app/observability/audit.py` | `audit.emit(ctx)` — passive sink that serializes `ctx.events` into one JSON log line |
| `app/safety/idempotency.py` | `IdempotencyStore` — in-memory TTL cache keyed by `user + tool + args` hash |

### Modified files

| File | Change |
|---|---|
| `app/main.py` | Added `logging.basicConfig` so audit logs stream to stdout |
| `app/api/routes/mcp.py` | Creates `ctx` per request; `try/finally` ensures `audit.emit(ctx)` fires on every exit |
| `app/auth/token_auth.py` | Records `auth.extract` + `auth.lookup` events; token hint (6 chars) instead of full token |
| `app/mcp/dispatcher.py` | Idempotency check before upstream for mutating tools; `dispatch.complete` on every exit |
| `app/mcp/upstream.py` | Times the `httpx` POST; records `upstream.call` with `latency_ms` + HTTP status |
| `app/policy/engine.py` | Records `policy.evaluate` (allow/deny) and `safety.revertible` per tool |
| `config/policy.yaml` | Added `mutating`/`revertible` flags; `admin` added to `allowed_groups`; `create_bucket` example |

---

## 🔑 How the audit stream works

### `RequestContext` (`app/observability/context.py`)
```python
@dataclass
class RequestContext:
    request_id: str       # UUID, unique per request
    method: str           # MCP method name
    principal: Principal  # authenticated user
    events: list[dict]    # ordered list of stage records
    started_at: float     # monotonic start time

    def record(self, stage: str, **fields) -> None:
        self.events.append({
            "stage": stage,
            "t_ms": round((time.monotonic() - self.started_at) * 1000, 2),
            **fields,
        })
```

### `IdempotencyStore` (`app/safety/idempotency.py`)
```python
# Key = SHA-256(user_id + tool + args)[:32]  or  explicit key from params
# TTL = 3600s (in-memory dict, resets on restart)
# Only triggered when policy.yaml has mutating: true for the tool
```

### `config/policy.yaml` — tool flags added in Phase 4
```yaml
get_weather:
  mutating: false                       # → no idempotency, no safety event for revert

delete_user:
  mutating: true                        # → idempotency check runs
  revertible: false                     # → can't be undone
  allow: false                          # ← normally denied; flip for idempotency test

create_bucket:                          # future tool example
  mutating: true
  revertible: true
  compensating_tool: "delete_bucket"   # → what Phase 5 would call to undo it
```

---

## 🧪 Tests — A B C D

All 9 tests passed. Below is each test with the exact audit output.

---

### 🅰️ Category A — Observability (4 tests)

**Purpose:** prove the audit stream records the right events in the right order.
Watch Terminal 1 (nom-py console) while running each request.

---

#### Test A1 — Successful read-only call (alice → get_weather) ✅

**Input:**
```json
{ "jsonrpc": "2.0", "id": 100, "method": "tools/call",
  "params": { "name": "get_weather", "arguments": { "location": "Hyderabad" } },
  "token": "tok-alice" }
```

**Client response:**
```json
{ "jsonrpc": "2.0", "id": 100,
  "result": { "content": [{ "type": "text", "text": "Weather in Hyderabad: 72°F, sunny." }], "isError": false } }
```

**Audit log (nom-py console):**
```json
{
  "request_id": "783a8cf3-041b-40b4-9a9c-05431ae9c12d",
  "user_id": "alice",
  "method": "tools/call",
  "duration_ms": 264.99,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.02,   "source": "body", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.06,   "token_hint": "tok-al…", "result": "ok", "user_id": "alice" },
    { "stage": "policy.evaluate",   "t_ms": 0.26,   "tool": "get_weather", "decision": "allow", "reason": "rule matched" },
    { "stage": "safety.revertible", "t_ms": 0.27,   "tool": "get_weather", "mutating": false, "revertible": false },
    { "stage": "upstream.call",     "t_ms": 264.95, "latency_ms": 264.6, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 264.98, "outcome": "ok" }
  ]
}
```

**What to observe:** 6 events present, `t_ms` values increase monotonically. `safety.revertible` shows `mutating: false` — idempotency block is skipped entirely for read-only tools. Full token never appears; only `"tok-al…"`.

---

#### Test A2 — Policy-denied call (bob → get_weather) ✅

**Input:**
```json
{ "jsonrpc": "2.0", "id": 101, "method": "tools/call",
  "params": { "name": "get_weather", "arguments": { "location": "Hyderabad" } },
  "token": "tok-bob" }
```

**Client response:**
```json
{ "jsonrpc": "2.0", "id": 101,
  "error": { "code": -32003, "message": "Tool 'get_weather' requires one of groups: ['developers', 'admin']" } }
```

**Audit log:**
```json
{
  "request_id": "0949c334-e54a-4c43-8efb-e462918bfcdf",
  "user_id": "bob",
  "method": "tools/call",
  "duration_ms": 0.62,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.02, "source": "body", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.04, "token_hint": "tok-bo…", "result": "ok", "user_id": "bob" },
    { "stage": "policy.evaluate",   "t_ms": 0.58, "tool": "get_weather", "decision": "deny",
      "reason": "not in allowed_groups=['developers', 'admin']" },
    { "stage": "dispatch.complete", "t_ms": 0.61, "outcome": "error" }
  ]
}
```

**What to observe:** Pipeline short-circuited at the policy gate. `safety.revertible` and `upstream.call` are **absent** — they never ran. `duration_ms: 0.62` confirms no upstream hop. The absence of events is the evidence.

---

#### Test A3 — Auth-denied call (invalid token) ✅

**Input:**
```json
{ "jsonrpc": "2.0", "id": 102, "method": "tools/list", "token": "tok-nobody" }
```

**Client response:**
```json
{ "jsonrpc": "2.0", "id": 102, "error": { "code": -32001, "message": "Invalid token" } }
```

**Audit log:**
```json
{
  "request_id": "16174af4-3bd0-4153-845d-aaa7c8097c9f",
  "user_id": null,
  "method": "tools/list",
  "duration_ms": 0.07,
  "events": [
    { "stage": "auth.extract", "t_ms": 0.01, "source": "body", "found": true },
    { "stage": "auth.lookup",  "t_ms": 0.03, "token_hint": "tok-no…", "result": "invalid" }
  ]
}
```

**What to observe:** Only 2 events — killed at the auth stage. `user_id: null` because no `Principal` was ever built. `policy.evaluate` is absent — policy never ran. Fastest possible failure path (`0.07ms`).

---

#### Test A4 — Token hint privacy ✅

Look at `auth.lookup` in any of the above audit logs:
- `"token_hint": "tok-al…"` — first 6 chars only
- `"tok-bo…"`, `"tok-no…"`, `"nom-ad…"` — same pattern for every token
- **Full token strings never appear anywhere in the audit log.**

This is security-critical. Audit logs often end up in shared systems (Splunk, ELK). A full token in a log = a credential leak.

---

### 🅱️ Category B — Admin token (1 test)

**Purpose:** `nom-admin-secret` was previously a dead config key. Phase 4 closes that gap.

---

#### Test B1 — Admin token as first-class principal ✅

**Input:**
```json
{ "jsonrpc": "2.0", "id": 200, "method": "tools/call",
  "params": { "name": "get_weather", "arguments": { "location": "Delhi" } },
  "token": "nom-admin-secret" }
```

**Client response:** successful weather result (same as alice).

**Audit log:**
```json
{
  "request_id": "f7e337bd-4284-4667-b157-fe3a30501395",
  "user_id": "admin",
  "method": "tools/call",
  "duration_ms": 270.53,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.01, "source": "body", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.03, "token_hint": "nom-ad…", "result": "admin", "user_id": "admin" },
    { "stage": "policy.evaluate",   "t_ms": 0.36, "tool": "get_weather", "groups": ["admin"], "decision": "allow" },
    { "stage": "safety.revertible", "t_ms": 0.37, "mutating": false, "revertible": false },
    { "stage": "upstream.call",     "t_ms": 270.51, "latency_ms": 269.91, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 270.53, "outcome": "ok" }
  ]
}
```

**What to observe:** `result: "admin"` in `auth.lookup` — the special admin path. `groups: ["admin"]` in `policy.evaluate` — no bypass code, admin participates in the same policy pipeline as everyone else. Globally-denied tools (`delete_user`) are **still denied** for admin — `allow: false` in YAML means globally denied, no exceptions.

---

### 🅲️ Category C — Idempotency (2 tests, 3 actual calls)

**Purpose:** mutating tools must not execute twice for the same request. Same inputs = cached result, upstream not called.

**Setup required:** `delete_user` is globally denied by default. Idempotency only runs after policy allows the call. To test, temporarily flip in `config/policy.yaml`:

```yaml
delete_user:
  allow: true                        # ← flip to true
  allowed_groups: ["developers", "admin"]
  mutating: true
  revertible: false
```

Uvicorn's `--reload` picks this up automatically.

---

#### Test C1 — Before the flip (policy still denied) — shows why staging matters

Before flipping the YAML, two calls to `delete_user` were sent. Both show:

```json
{
  "user_id": "alice", "duration_ms": 0.84,
  "events": [
    { "stage": "auth.extract" },
    { "stage": "auth.lookup",     "result": "ok" },
    { "stage": "policy.evaluate", "decision": "deny",
      "reason": "destructive operations not permitted via this gateway" },
    { "stage": "dispatch.complete", "outcome": "error" }
  ]
}
```

**Key point:** idempotency was never reached. The pipeline died at `policy.evaluate`. The idempotency block only runs after policy grants `allow`. This is the correct design — there's nothing to cache for a denied request.

---

#### Test C1 — Idempotency MISS (first call after YAML flip) ✅

**Input (sent once):**
```json
{ "jsonrpc": "2.0", "id": 300, "method": "tools/call",
  "params": { "name": "delete_user", "arguments": { "user_id": "alice" } },
  "token": "tok-alice" }
```

**Audit log — MISS (11:56:43):**
```json
{
  "request_id": "be7d14ce-323c-4ade-8dc3-c5d36712ba68",
  "user_id": "alice",
  "method": "tools/call",
  "duration_ms": 262.14,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.02, "source": "body", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.04, "token_hint": "tok-al…", "result": "ok" },
    { "stage": "policy.evaluate",   "t_ms": 0.35, "tool": "delete_user", "decision": "allow" },
    { "stage": "safety.revertible", "t_ms": 0.36, "mutating": true, "revertible": false },
    { "stage": "idempotency.miss",  "t_ms": 0.77, "key": "2f54dd9e53f3d464eb193c631d527bbb" },
    { "stage": "upstream.call",     "t_ms": 262.12, "latency_ms": 261.3, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 262.14, "outcome": "ok" }
  ]
}
```

**What happened:** `idempotency.miss` → key computed, nothing in cache → upstream was called (262ms real execution) → result cached under that key.

---

#### Test C1 — Idempotency HIT (second + third identical calls) ✅

**Same input sent again (twice more):**

**Audit log — HIT 1 (12:01:29):**
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

**Audit log — HIT 2 (12:01:30):**
```json
{
  "request_id": "51892c1e-90bd-4eec-a297-fe4e29dd0d5f",
  "user_id": "alice",
  "duration_ms": 0.69,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.02 },
    { "stage": "auth.lookup",       "t_ms": 0.05, "result": "ok" },
    { "stage": "policy.evaluate",   "t_ms": 0.38, "decision": "allow" },
    { "stage": "safety.revertible", "t_ms": 0.39, "mutating": true },
    { "stage": "idempotency.hit",   "t_ms": 0.67, "key": "2f54dd9e53f3d464eb193c631d527bbb" },
    { "stage": "dispatch.complete", "t_ms": 0.69, "outcome": "ok" }
  ]
}
```

**What to observe — miss vs hit comparison:**

| | Miss (11:56:43) | Hit 1 (12:01:29) | Hit 2 (12:01:30) |
|---|---|---|---|
| `duration_ms` | **262.14ms** | **0.39ms** | **0.69ms** |
| `upstream.call` | ✅ present (261ms) | ❌ absent | ❌ absent |
| `idempotency` event | `idempotency.miss` | `idempotency.hit` | `idempotency.hit` |
| Key | `2f54dd9e…` | `2f54dd9e…` (same) | `2f54dd9e…` (same) |
| Upstream actually called | Yes | **No** | **No** |

**~670× speedup.** More importantly: the **semantic guarantee** is the point — nom-py refused to re-execute a mutating side effect. `delete_user` was only sent to the upstream once. The same response was returned for calls 2 and 3 from cache.

**The key is deterministic:** `SHA-256(user_id="alice" + tool="delete_user" + args={"user_id":"alice"})[:32]` = `2f54dd9e53f3d464eb193c631d527bbb`. Same inputs always produce the same key.

---

#### Test C2 — Read-only tools bypass idempotency entirely ✅

**Input (get_weather, sent twice):**
```json
{ "jsonrpc": "2.0", "id": 400, "method": "tools/call",
  "params": { "name": "get_weather", "arguments": { "location": "Bangalore" } },
  "token": "tok-alice" }
```

**Both audit logs:**
```json
{
  "events": [
    { "stage": "auth.extract" },
    { "stage": "auth.lookup",       "result": "ok" },
    { "stage": "policy.evaluate",   "decision": "allow" },
    { "stage": "safety.revertible", "mutating": false, "revertible": false },
    { "stage": "upstream.call",     "latency_ms": 267.72, "status": 200 },
    { "stage": "dispatch.complete", "outcome": "ok" }
  ]
}
```

**What to observe:** `safety.revertible` shows `mutating: false` — idempotency block is skipped entirely for both calls. Both have `upstream.call` — the real upstream was hit both times. No `idempotency.miss` or `idempotency.hit` event anywhere.

---

### 🅳 Category D — Phase 3 regression (1 test)

#### Test D1 — All Phase 3 scenarios unchanged ✅

All 4 client scenarios (no token / alice / bob / invalid) return byte-for-byte identical JSON-RPC responses to Phase 3. Phase 4 was a **purely additive refactor** — it added instrumentation without touching any client-visible response.

---

## ✅ Final test scorecard

| # | Test | Result |
|---|---|---|
| A1 | Successful trace — alice → get_weather | ✅ PASS |
| A2 | Policy-denied trace — bob → get_weather | ✅ PASS |
| A3 | Auth-denied trace — invalid token | ✅ PASS |
| A4 | Token hint privacy | ✅ PASS |
| B1 | Admin token as first-class principal | ✅ PASS |
| C1 | Idempotency miss (first mutating call) | ✅ PASS |
| C1 | Idempotency hit (repeat mutating call) | ✅ PASS |
| C2 | Read-only tools bypass idempotency | ✅ PASS |
| D1 | Phase 3 regression | ✅ PASS |

**9 / 9. Phase 4 complete.**

---

## 🧠 Key design principles

**Instrumentation is structural, not retrofitted.**
Events are recorded by each gate as it runs. Adding a new metrics sink or DB backend tomorrow = write one new consumer of `ctx.events`. No gate code changes.

**The audit record is honest.**
Every stage that ran appears in the record. Every stage that didn't run is absent. The missing events are the evidence. An auth failure with 2 events proves the request died at auth.

**Idempotency is scoped to mutating tools only.**
`mutating: false` in `policy.yaml` → idempotency block skipped entirely. This is correct — caching read-only results would be pointless and waste memory.

**Admin fits the policy model, it doesn't bypass it.**
`nom-admin-secret` maps to `Principal(groups=["admin"])`. The same `evaluate_tool_call()` runs for admin as for any user. `allow: false` globally still means globally denied.

**Revert metadata is design-first.**
`revertible: true` + `compensating_tool: "delete_bucket"` declared in YAML now. Phase 4 records it in the audit stream. Actual compensation execution is Phase 5+ scope.

---

## ⛔ What Phase 4 explicitly did NOT include

- Persistent audit storage (stdout only; Splunk/DB later)
- Redis-backed idempotency (in-memory dict, resets on restart)
- Actually executing compensating actions (audit records the possibility)
- SSE / streaming, GitHub OAuth, stdio bridge for Claude Desktop

---

## 📊 Phase summary

| Layer | Phase | Status |
|---|---|---|
| HTTP + routing scaffold | 1 | ✅ |
| MCP forwarding pipeline | 2 | ✅ |
| Token auth + policy | 3 | ✅ |
| Audit stream + idempotency + revert metadata | 4 | ✅ |
| GitHub OAuth + Claude Desktop bridge + demo | 5 | ⏭️ Next |
