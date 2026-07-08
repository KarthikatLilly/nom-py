import pathlib

doc = """\
<style>
a { text-decoration: none; color: #464feb; }
tr th, tr td { border: 1px solid #e6e6e6; }
tr th { background-color: #f5f5f5; }
figure { margin: 16px 0; }
figcaption { font-size: 0.85em; color: #666; margin-top: 4px; }
figure img { border: 1px solid #e6e6e6; border-radius: 6px; display: block; }
</style>

# Phase 5 \u2014 Claude Desktop Integration \u2705

## Goal

Connect nom-py to a real, unmodified MCP client and prove that identity-aware
policy enforcement works end-to-end when the client is something you did not build.

---

## Why Claude Desktop? Not Swagger, not `cmd/client`

| Client | What it proves | Limitation |
|---|---|---|
| Swagger UI | Routes respond correctly | You control every request manually |
| `cmd/client/main.py` | Full flow works | You wrote it \u2014 cooperates by design |
| **Claude Desktop** | **Independent client, real MCP protocol, real AI judgment** | Nothing staged |

Claude Desktop is Anthropic\u2019s reference MCP client, built independently of nom-py.
It sends a real MCP handshake, respects the `tools/list` catalog, refuses to invent
capabilities, and asks human permission before calling tools. Getting it to work
with nom-py proves the gateway speaks MCP correctly \u2014 not just \u201cour test script says so.\u201d

---

## What Phase 5 adds

| File | Purpose |
|---|---|
| `cmd/stdio_bridge/main.py` | Translation shim: Claude stdio \u2194 nom-py HTTP. ~120 lines |
| `cmd/stdio_bridge/test_handshake.txt` | 4-line fixture for verifying the bridge without Claude Desktop |

**nom-py itself was not modified.** The bridge is 100% transport translation.

---

## \U0001f309 The stdio bridge

Claude Desktop only spawns **stdio MCP servers** and pipes JSON-RPC over stdin/stdout.
nom-py is an HTTP server. The bridge is the adapter:

```
Claude Desktop
    \u2502  spawns process
    \u25bc
cmd/stdio_bridge/main.py
    \u2502  stdin  \u2192 parse JSON-RPC line
    \u2502  POST http://localhost:8001/mcp  (Authorization: Bearer <token>)
    \u2502  response \u2192 stdout
    \u25bc
nom-py :8001  \u2192  enforce auth + policy + audit  \u2192  upstream :9001
```

### Design invariants

| Rule | Why |
|---|---|
| `stdout` = JSON-RPC responses only, one line each | Claude parses every stdout byte as MCP |
| `stderr` = all logs | Anything non-JSON on stdout crashes the parser |
| Notifications (no `id`) \u2192 **silence** on stdout | Claude sends `notifications/initialized` expecting no response |
| Non-JSON from nom-py \u2192 wrapped as JSON-RPC error | Protects against debug pages breaking Claude |
| Blocking stdin via `run_in_executor` | Keeps asyncio event loop alive for the httpx client |

### Token injection

```
NOM_URL    \u2014 nom-py endpoint  (default: http://localhost:8001/mcp)
NOM_TOKEN  \u2014 injected as Authorization: Bearer <token>
```

Two tokens = two Claude Desktop entries (`nom-py-alice`, `nom-py-bob`) = two identities, one gateway.

---

## \u2699\ufe0f Setup \u2014 Claude Desktop config

### Why the MSIX path

Claude Desktop on Windows is an MSIX package running in an app-container sandbox.
Config lives at:

```
%LOCALAPPDATA%\\Packages\\Claude_<hash>\\LocalCache\\Roaming\\Claude\\claude_desktop_config.json
```

Not `%APPDATA%\\Claude\\`. Writing to the wrong path is **silently ignored**.

### One-shot PowerShell config writer

```powershell
# Auto-detects the MSIX sandbox path, writes BOM-free UTF-8
$claudePath = Get-ChildItem "$env:LOCALAPPDATA\\Packages" -Directory -Filter "Claude_*" |
    Select-Object -First 1 -ExpandProperty FullName
$configPath = Join-Path $claudePath "LocalCache\\Roaming\\Claude\\claude_desktop_config.json"

[System.IO.File]::WriteAllText($configPath, $config, [System.Text.UTF8Encoding]::new($false))
Write-Host "Wrote to: $configPath" -ForegroundColor Green
```

| Detail | Why it matters |
|---|---|
| `UTF8Encoding::new($false)` | BOM-free UTF-8 \u2014 Claude silently fails to parse files with a BOM |
| `SystemRoot` + `PATH` in `env` | MSIX sandbox strips env variables; Python can\u2019t find its DLLs without them |
| Auto-detect `Claude_*` folder | The hash suffix changes; hard-coding it breaks on reinstall |

After writing \u2192 fully restart Claude Desktop (system tray \u2192 Quit \u2192 relaunch).

---

## \U0001f9ea Pre-Claude verification \u2014 bridge smoke test

`test_handshake.txt` sends 4 messages to verify the bridge works before involving Claude Desktop:

```
initialize
notifications/initialized   \u2190 no id = notification, expects stdout silence
tools/list
tools/call \u2192 get_weather (Hyderabad)
```

**alice** (`NOM_TOKEN=tok-alice`) \u2014 2 tools returned, weather executes:

```
[stdio-bridge] \u2192 initialize id=1
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","serverInfo":{"name":"nom-py","version":"0.4.0"},...}}
[stdio-bridge] \u2192 notifications/initialized (notification)
[stdio-bridge] \u2190 notification ack (status=204, no stdout)          \u2190 correct: silence
[stdio-bridge] \u2192 tools/list id=2
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"get_weather",...},{"name":"list_users",...}]}}
[stdio-bridge] \u2192 tools/call id=3
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"Weather in Hyderabad: 72\u00b0F, sunny."}],"isError":false}}
[stdio-bridge] stdin closed, exiting
```

**bob** (`NOM_TOKEN=tok-bob`) \u2014 1 tool returned, get_weather denied:

```
[stdio-bridge] \u2192 tools/list id=2
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"list_users",...}]}}        \u2190 1 tool only

[stdio-bridge] \u2192 tools/call id=3
{"jsonrpc":"2.0","id":3,"error":{"code":-32003,"message":"Tool 'get_weather' requires one of groups: ['developers', 'admin']"}}
```

**no token** (`NOM_TOKEN=""`) \u2014 auth gate fires on every non-initialize call:

```
[stdio-bridge] token: anonymous
[stdio-bridge] \u2192 tools/list id=2
{"jsonrpc":"2.0","id":2,"error":{"code":-32001,"message":"Missing token"}}
```

nom-py audit for no-token \u2014 1 event only, pipeline died at auth:

```json
{
  "user_id": null,
  "method": "tools/call",
  "duration_ms": 0.02,
  "events": [
    { "stage": "auth.extract", "t_ms": 0.01, "source": null, "found": false }
  ]
}
```

---

## \U0001f3ac Live demo \u2014 5 scenarios

---

### Scenario 1 \u2014 Alice\u2019s tool catalog

**Prompt:** *\u201cUse nom-py-alice to list all tools you have available\u201d*

<figure>
<img src="clade-tools-nom-py-alice.png" width="520">
<figcaption><strong>nom-py-alice \u2014 Claude Desktop sees 2 tools:</strong> <code>get_weather</code> and <code>list_users</code>. <code>delete_user</code> is absent \u2014 filtered out by nom-py before Claude ever received the list.</figcaption>
</figure>

`filter_tools_list(alice)` evaluated all 3 upstream tools:

| Tool | Alice\u2019s groups | Decision |
|---|---|---|
| `get_weather` | developers \u2705 | allow \u2014 shown |
| `list_users` | analysts \u2705 | allow \u2014 shown |
| `delete_user` | `allow: false` globally | deny \u2014 **hidden** |

**Audit \u2014 tools/list:**

```json
{
  "user_id": "alice",
  "method": "tools/list",
  "duration_ms": 4.44,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.01, "source": "header", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.02, "token_hint": "tok-al\u2026", "result": "ok", "user_id": "alice" },
    { "stage": "upstream.call",     "t_ms": 3.72, "latency_ms": 3.49, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 4.43, "outcome": "ok" }
  ]
}
```

> `policy.evaluate` is not in the audit for `tools/list` because `filter_tools_list()`
> evaluates internally to build the filtered response. The filtering is visible in what\u2019s
> *absent* from the catalog Claude received.

---

### Scenario 2 \u2014 Alice executes an allowed tool

**Prompt:** *\u201cGet me the weather in Hyderabad using nom-py-alice\u201d*

<figure>
<img src="claude-weather-nom-py-alice.png" width="520">
<figcaption><strong>nom-py-alice \u2014 weather result:</strong> Claude Desktop returns \u201cWeather in Hyderabad: 72\u00b0F, sunny\u201d after asking permission and receiving a successful response from nom-py.</figcaption>
</figure>

**Audit \u2014 tools/call get_weather \u2014 full 6-stage lifecycle:**

```json
{
  "request_id": "e813c93d-7316-4455-8724-c29b8dd1183c",
  "user_id": "alice",
  "method": "tools/call",
  "duration_ms": 268.41,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.01, "source": "header", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.03, "token_hint": "tok-al\u2026", "result": "ok", "user_id": "alice" },
    { "stage": "policy.evaluate",   "t_ms": 0.24, "tool": "get_weather", "user": "alice",
      "groups": ["developers", "analysts"], "decision": "allow", "reason": "rule matched" },
    { "stage": "safety.revertible", "t_ms": 0.24, "tool": "get_weather",
      "mutating": false, "revertible": false, "compensating_tool": null },
    { "stage": "upstream.call",     "t_ms": 268.35, "latency_ms": 268.03, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 268.37, "outcome": "ok" }
  ]
}
```

All 6 stages ran. `t_ms` values increase monotonically. The bulk of time (268ms) is the
real upstream HTTP call \u2014 everything in nom-py itself took under 0.5ms.
Token came from `Authorization: Bearer` header \u2014 Claude Desktop uses the header, not the body.

---

### Scenario 3 \u2014 Bob\u2019s restricted catalog

**Prompt:** *\u201cUse nom-py-bob to list all tools you have available\u201d*

<figure>
<img src="clade-tools-nom-py-bob.png" width="520">
<figcaption><strong>nom-py-bob \u2014 Claude Desktop sees 1 tool:</strong> <code>list_users</code> only. Same gateway, different token, smaller world.</figcaption>
</figure>

`filter_tools_list(bob)` \u2014 same upstream, different result:

| Tool | Bob\u2019s groups | Decision |
|---|---|---|
| `get_weather` | analysts \u274c (needs developers) | deny \u2014 **hidden** |
| `list_users` | analysts \u2705 | allow \u2014 shown |
| `delete_user` | globally denied | deny \u2014 **hidden** |

**Audit \u2014 tools/list for bob:**

```json
{
  "user_id": "bob",
  "method": "tools/list",
  "duration_ms": 4.44,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.01, "source": "header", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.02, "token_hint": "tok-bo\u2026", "result": "ok", "user_id": "bob" },
    { "stage": "upstream.call",     "t_ms": 3.72, "latency_ms": 3.49, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 4.43, "outcome": "ok" }
  ]
}
```

**Audit \u2014 tools/call get_weather for bob (policy short-circuit, 0.42ms):**

```json
{
  "request_id": "875da555-7ae6-48a7-9271-4f9130e87c30",
  "user_id": "bob",
  "method": "tools/call",
  "duration_ms": 0.42,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.01, "source": "header", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.02, "token_hint": "tok-bo\u2026", "result": "ok", "user_id": "bob" },
    { "stage": "policy.evaluate",   "t_ms": 0.39, "tool": "get_weather", "user": "bob",
      "groups": ["analysts"], "decision": "deny",
      "reason": "not in allowed_groups=['developers', 'admin']" },
    { "stage": "dispatch.complete", "t_ms": 0.41, "outcome": "error" }
  ]
}
```

`upstream.call` is **absent** \u2014 killed at the policy gate. 0.42ms vs 268ms for a success.

---

### Scenario 4 \u2014 Bob asks for a hidden tool

**Prompt:** *\u201cUse nom-py-bob to get the weather in Delhi\u201d*

**Claude\u2019s response:** *\u201cThe nom-py-bob server only exposes `list_users`. There is no weather tool available.\u201d*

**No audit line generated.** Claude never sent a request to nom-py because `get_weather`
was not in the catalog it received. The client refused to hallucinate a capability.

> **The strongest enforcement is invisibility, not rejection.**
>
> Rejection at call time says \u201cthis exists but you cannot have it.\u201d
> Filtering at catalog level says \u201cthis does not exist.\u201d The client never tries.

---

### Scenario 5 \u2014 Alice tries to delete a user

**Prompt:** *\u201cUse nom-py-alice to delete user \u2018alice\u2019\u201d*

<figure>
<img src="delete-alice-not-pos.png" width="520">
<figcaption><strong>nom-py-alice \u2014 delete refused:</strong> Claude Desktop re-verified the catalog and correctly reports no delete capability exists through this server.</figcaption>
</figure>

Claude re-called `tools/list` on nom-py-alice before acting (it verifies server state
rather than trusting the user\u2019s claim). Catalog returned: `get_weather` + `list_users`.
Claude refused and called `list_users` to demonstrate what Alice actually can do.

<figure>
<img src="delete-user-allow.png" width="520">
<figcaption><strong>nom-py-alice \u2014 list_users instead:</strong> Claude confirms alice, bob, charlie exist but explains no delete operation is available through this server.</figcaption>
</figure>

**Audit \u2014 tools/call list_users (the call Claude made after refusing delete):**

```json
{
  "request_id": "2db6c782-4e90-44f0-8942-7be20925eb50",
  "user_id": "alice",
  "method": "tools/call",
  "duration_ms": 268.27,
  "events": [
    { "stage": "auth.extract",      "t_ms": 0.06, "source": "header", "found": true },
    { "stage": "auth.lookup",       "t_ms": 0.09, "token_hint": "tok-al\u2026", "result": "ok", "user_id": "alice" },
    { "stage": "policy.evaluate",   "t_ms": 0.42, "tool": "list_users", "user": "alice",
      "groups": ["developers", "analysts"], "decision": "allow", "reason": "rule matched" },
    { "stage": "safety.revertible", "t_ms": 0.43, "tool": "list_users",
      "mutating": false, "revertible": false, "compensating_tool": null },
    { "stage": "upstream.call",     "t_ms": 268.24, "latency_ms": 267.65, "status": 200 },
    { "stage": "dispatch.complete", "t_ms": 268.27, "outcome": "ok" }
  ]
}
```

**No audit line for delete** \u2014 nom-py was never asked. Prevention happened entirely at
the catalog layer. The policy engine was never consulted for that action.

---

## \u2705 What this demo proved

| Behavior | Evidence |
|---|---|
| Bridge speaks correct MCP protocol | `notifications/initialized` \u2192 204, no stdout |
| Alice gets 2-tool filtered catalog | Screenshot + tools/list audit |
| Alice executes allowed tool end-to-end | Screenshot + full 6-stage audit |
| Bob gets 1-tool filtered catalog | Screenshot + tools/list audit |
| Bob\u2019s tools/call denied at policy gate | 0.42ms audit, no `upstream.call` |
| Bob cannot access a hidden tool | Claude refused \u2014 no nom-py request sent |
| Alice cannot see or invoke `delete_user` | Claude verified catalog, refused to hallucinate |
| Every request produces a structured audit trace | Audit logs for all scenarios |
| nom-py unmodified for Phase 5 | Bridge is 100% transport translation |

---

## \U0001f511 Layered defense model

nom-py enforces policy at two independent layers:

**Layer 1 \u2014 Catalog (`tools/list`):** `filter_tools_list()` removes tools the
principal cannot call. The client never learns forbidden tools exist.

**Layer 2 \u2014 Call (`tools/call`):** `evaluate_tool_call()` denies if a client
calls a tool not in its catalog. Belt-and-suspenders backup.

Claude Desktop exercised Layer 1 in every scenario \u2014 re-verified the catalog when
challenged, refused to invent capabilities, and only called tools explicitly given.
nom-py filtering + Claude cooperative behavior = mistakes nearly impossible without
deliberate policy changes.

**The strongest denial is the one where the client never knew the option existed.**

---

## \u26d4 What Phase 5 did NOT prove

- Production auth (OAuth/OBO \u2014 Phase 6+)
- Concurrent-request safety at real scale
- Multi-tenant isolation beyond token-mapped groups
- Compatibility with MCP clients other than Claude Desktop
- Any performance claims

---

## \U0001f4ca Phase summary

| Layer | Phase | Status |
|---|---|---|
| HTTP + routing scaffold | 1 | \u2705 |
| MCP forwarding pipeline | 2 | \u2705 |
| Token auth + policy enforcement | 3 | \u2705 |
| Audit stream + idempotency + revert metadata | 4 | \u2705 |
| stdio bridge + Claude Desktop integration | 5 | \u2705 |
| GitHub OAuth + production hardening | 6 | \u23ed\ufe0f Next |
"""

pathlib.Path("c:/Users/L132478/nom-py/docs/phase5_guardrails.md").write_text(doc, encoding="utf-8")
print(f"Written: {doc.count(chr(10))} lines, {len(doc)} chars")
