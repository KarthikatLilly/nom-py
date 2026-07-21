# Phase 6 — Outbound Credentials (AuthProvider Layer) ✅

## Goal

Phases 1–5 built inbound identity (`Principal`) and policy (`PolicyEngine`) — they
answer "who is calling nom-py, and are they allowed to call this tool?" Neither
question says anything about how nom-py itself authenticates *to the upstream*
once a call is allowed. Phase 6 adds that missing layer: a per-upstream
`AuthProvider` abstraction that resolves an outbound credential for every tool
call, without the dispatcher ever branching on which upstream it's talking to.

This is a local demo. No real GitHub, Google, GCP, or enterprise vault API is
called anywhere in this phase — every provider talks to an in-process fake
client, and every point where a real SDK call belongs is marked with a
`# REAL: replace with <sdk call>` comment. The *shape* of the abstraction and
the *ordering* of the security checks are meant to be production-representative;
only the I/O underneath is faked.

---

## Two auth questions, kept separate on purpose

| | Inbound identity | Outbound credential |
|---|---|---|
| Question | Who is calling nom-py? | How does nom-py call the upstream, as that user? |
| Type | `Principal` | `UpstreamCredential` |
| Where decided | `app/auth/token_auth.py` (Phases 1–5) | `app/auth/providers/*` (Phase 6) |
| Changed in Phase 6? | **No** | **Yes — new** |

It would be tempting to fold these into one concept, but they answer different
questions and change independently. A user's inbound token identifies *them* to
nom-py — it says nothing about which GitHub PAT, Google OAuth token, or vault
lease nom-py should present to an upstream on their behalf. Keeping them separate
means adding a fifth upstream with a fifth auth scheme never touches
`token_auth.py`, `Principal`, or the policy engine at all.

---

## Why not `if upstream == "github": ... elif ...`

The naive approach is a branch per upstream inside the dispatcher. It works for
two upstreams. It rots at four, and it mixes three unrelated concerns in one
function: *which* upstream, *what* credential scheme, and *whether the call is
even allowed*.

Phase 6 replaces the branch with a lookup table:

```
ServerConfig.auth_mode  →  ProviderRegistry  →  AuthProvider
     ("pat"/"oauth"/"cli"/"ca")   (dict lookup)      (interface)
```

The dispatcher's only touchpoint is the `AuthProvider` interface
(`get_upstream_credentials`, `release`). It has zero knowledge of PATs, OAuth
refresh flows, GCP impersonation, or vault leases — that knowledge lives
entirely inside each provider. Adding a fifth auth mode means: write a new
`AuthProvider` subclass, register it in `default_registry()`, done. The
dispatcher file does not change.

---

## The abstraction (`app/auth/providers/base.py`)

```python
@dataclass
class UpstreamCredential:
    headers: dict[str, str]
    expires_at: float | None = None
    lease_id: str | None = None   # audit reference — NEVER the secret itself

class AuthProvider(ABC):
    @abstractmethod
    async def get_upstream_credentials(self, principal, upstream) -> UpstreamCredential: ...

    async def release(self, cred: UpstreamCredential) -> None:
        return None   # default no-op
```

Two design choices worth calling out:

- **`lease_id` is not the secret.** It's an opaque reference the audit trail can
  safely record. The actual secret only ever lives inside `headers`, which is
  never logged (see [Audit safety](#audit-safety-lease_id-in-never-the-secret)
  below).
- **`release()` defaults to a no-op.** Most credential types (a static PAT, a
  cached OAuth token) have nothing to release. Only `EnterpriseCAProvider`
  overrides it — see [Why CA is different](#why-enterprise-ca-is-structurally-different).

`ConfigError` (also in `base.py`) is the single exception type both
`ProviderRegistry.for_upstream()` and `ServerRegistry.resolve()` raise for
anything unrecognized — an unknown `auth_mode`, an unknown namespace, an
unnamespaced tool name. It exists so the dispatcher can catch one exception
type and know "this is a configuration problem, fail closed," rather than
guessing from a bare `KeyError`.

---

## Server + namespace routing (`app/mcp/server_registry.py`)

Each upstream in `config/servers.yaml` gets a `ServerConfig`:

```yaml
servers:
  github:
    url: "http://localhost:9001/mcp"
    namespace: "github"
    auth_mode: "pat"

  google:
    url: "http://localhost:9001/mcp"
    namespace: "google"
    auth_mode: "oauth"

  gcp:
    url: "http://localhost:9001/mcp"
    namespace: "gcp"
    auth_mode: "cli"
    service_account: "nom-gcp-runner@example-project.iam.gserviceaccount.com"

  internal:
    url: "http://localhost:9001/mcp"
    namespace: "internal"
    auth_mode: "ca"
    vault_safe: "MCP-Internal-CA"
```

(All four point at the same local mock upstream on `:9001` for this demo — in a
real deployment each would be a distinct upstream MCP server.)

Every tool nom-py exposes is namespaced as `"<namespace>__<tool_name>"` — e.g.
`github__list_repos`, `internal__get_weather`. This lets one flat `tools/list`
mix tools from four different upstreams without name collisions (`get_weather`
could exist on both `internal` and some future `weather-api` server without
ambiguity).

`ServerRegistry.resolve(exposed_tool)` splits that back apart:

```python
def resolve(self, exposed_tool: str) -> tuple[ServerConfig, str]:
    namespace, _, original_name = exposed_tool.partition("__")
    server = self._by_namespace.get(namespace)
    if server is None:
        raise ConfigError(...)
    return server, original_name
```

`github__get_weather` → `(ServerConfig(name="github", auth_mode="pat", ...), "get_weather")`.
The `original_name` is what actually gets forwarded to the upstream, and what
`policy.yaml` rules are keyed on — the same `get_weather` rule applies
regardless of which namespace exposed it.

`vault_safe` and `service_account` are optional fields only `ca` and `cli`
servers need — see their provider sections below for what happens if they're
missing.

---

## The registry (`app/auth/providers/registry.py`)

```python
class ProviderRegistry:
    def for_upstream(self, upstream: ServerConfig) -> AuthProvider:
        try:
            return self._providers[upstream.auth_mode]
        except KeyError:
            raise ConfigError(f"No AuthProvider registered for auth_mode '{upstream.auth_mode}'")
```

A plain `dict[str, AuthProvider]` lookup. `default_registry()` wires the four
concrete providers to their string keys:

```python
def default_registry() -> ProviderRegistry:
    return ProviderRegistry({
        "pat":   GitHubPATProvider(),
        "oauth": GoogleOAuthProvider(),
        "cli":   GCPCLIProvider(),
        "ca":    EnterpriseCAProvider(),
    })
```

**Fail closed on unknown mode.** If `config/servers.yaml` ever declares
`auth_mode: "smartcard"` and no provider is registered for it, `for_upstream()`
raises `ConfigError` rather than silently falling back to some default
provider. The dispatcher turns that into a `-32000` error and the call never
proceeds — an unrecognized auth mode is treated as "we don't know how to
authenticate this, so we don't" rather than "guess and hope."

---

## The four providers, in depth

Each provider file has exactly one job: turn `(principal, upstream)` into an
`UpstreamCredential`. Below is what each one is configured with, how it behaves,
and — critically — where the `# REAL:` marker sits for the eventual real
integration.

### `pat` — `GitHubPATProvider` (`app/auth/providers/pat.py`)

The simplest case: a personal access token is a long-lived, static secret keyed
by user. No refresh, no expiry, no release.

```python
async def get_upstream_credentials(self, principal, upstream) -> UpstreamCredential:
    # REAL: replace with a call to the org's secret manager (e.g. AWS Secrets
    # Manager, HashiCorp Vault KV) scoped to principal.user_id.
    pat = self._store.get_pat(principal.user_id)
    return UpstreamCredential(headers={"Authorization": f"Bearer {pat}"})
```

`FakeSecretStore` (in `fakes.py`) is a `dict[user_id, pat]` with two seeded
users (`alice`, `bob`). In production this becomes a lookup into a real secret
manager, still scoped by `principal.user_id` — the shape of the call doesn't
change, only what's on the other end of `get_pat()`.

**Configuration:** none beyond `auth_mode: "pat"`. No optional fields needed.

### `oauth` — `GoogleOAuthProvider` (`app/auth/providers/oauth.py`)

OAuth access tokens are short-lived by design (Google's typically last ~1 hour).
Minting a fresh one on every call would be wasteful and slow, so this provider
caches per-user until expiry:

```python
async def get_upstream_credentials(self, principal, upstream) -> UpstreamCredential:
    cached = self._cache.get(principal.user_id)
    now = time.time()
    if cached is not None and cached[1] > now:
        access_token, expires_at = cached
    else:
        # REAL: replace with POST https://oauth2.googleapis.com/token
        # (refresh_token grant) using the user's stored refresh token.
        minted = self._endpoint.mint_access_token(principal.user_id)
        access_token, expires_at = minted["access_token"], now + minted["expires_in"]
        self._cache[principal.user_id] = (access_token, expires_at)
    return UpstreamCredential(headers={"Authorization": f"Bearer {access_token}"}, expires_at=expires_at)
```

`FakeOAuthTokenEndpoint.mint_access_token()` counts calls (`self.calls`), which
is exactly what [`test_providers.py`](../tests/test_providers.py) uses to prove
caching actually works: two calls within the TTL window hit the fake endpoint
exactly once.

**What's missing for real use** (called out explicitly, not glossed over): a
real deployment needs a persisted **refresh token** per user — obtained once
through a normal OAuth consent flow — that this provider would exchange for
access tokens. That refresh-token storage and the initial consent flow are out
of scope for Phase 6; the `# REAL:` marker is where that exchange would happen.

**Configuration:** none beyond `auth_mode: "oauth"`.

### `cli` — `GCPCLIProvider` (`app/auth/providers/cli.py`)

This one has an explicit anti-goal: **never read a local `gcloud`/ADC session.**
nom-py is a shared multi-tenant service; if it silently picked up whatever
identity happened to be logged into the host machine's CLI, every call would
run as whoever last ran `gcloud auth login` on that box — a hidden, ambient
credential completely disconnected from `principal.user_id`. Instead, this
provider always mints a fresh, explicitly impersonated token:

```python
async def get_upstream_credentials(self, principal, upstream) -> UpstreamCredential:
    service_account = upstream.service_account
    if not service_account:
        raise ValueError(f"Server '{upstream.name}' has no service_account configured for cli auth_mode")

    # REAL: replace with IAM Credentials API generateAccessToken, impersonating
    # `service_account` (never a local `gcloud auth` session).
    minted = self._minter.impersonate(service_account)
    return UpstreamCredential(headers={"Authorization": f"Bearer {minted['token']}"}, expires_at=...)
```

If `service_account` is missing from the server's config, this raises before
ever touching the (fake) minter — the dispatcher's fail-closed `except
Exception` around credential resolution turns that into a clean `-32000`
rather than a stack trace reaching the upstream.

**Configuration:** requires `service_account: "<sa-email>"` in
`config/servers.yaml` for any server using `auth_mode: "cli"`. This is the
identity being impersonated — every call through this upstream authenticates
as this service account, scoped by whatever IAM permissions it's been granted,
not as whatever identity is logged in locally.

### `ca` — `EnterpriseCAProvider` (`app/auth/providers/ca.py`)

The odd one out — see the dedicated section below.

```python
async def get_upstream_credentials(self, principal, upstream) -> UpstreamCredential:
    safe = upstream.vault_safe
    if not safe:
        raise ValueError(f"Server '{upstream.name}' has no vault_safe configured for ca auth_mode")

    # REAL: replace with a CyberArk Central Credential Provider / Conjur lease call.
    lease = self._vault.lease(safe=safe, requested_by=principal.user_id)
    return UpstreamCredential(
        headers={"Authorization": f"Bearer {lease.secret}"},
        expires_at=lease.expires_at,
        lease_id=lease.id,
    )

async def release(self, cred: UpstreamCredential) -> None:
    if cred.lease_id:
        # REAL: replace with the vault's lease-revoke call.
        self._vault.invalidate(cred.lease_id)
```

**Configuration:** requires `vault_safe: "<safe-name>"` in
`config/servers.yaml`. The term "Enterprise CA" here refers to a generic
enterprise credential-vaulting system (the kind of dynamic-secrets vault
product used in large organizations) — this codebase intentionally does not
name or integrate with any specific vendor or company system. The demo's fake,
`FakeVaultClient`, is enough to exercise the exact same lease/release
contract a real vault client would expose.

---

## Why Enterprise CA is structurally different

`pat`, `oauth`, and `cli` all reduce to the same shape: call something, get a
token, hand it over, forget about it. `ca` breaks that pattern in two ways that
matter for how the dispatcher has to treat it.

### 1. It issues a lease, not a bare token

A vault lease isn't just a secret value — it's a *checkout record*. The vault
tracks that safe `MCP-Internal-CA` currently has an outstanding lease, who
requested it (`requested_by=principal.user_id`), and when it expires. That
checkout record has an identity of its own: `lease.id`. This is why
`UpstreamCredential` has a `lease_id` field that none of the other three
providers ever populate — it's specific to credential systems that track
checkouts, not just credential systems that hand out tokens.

That `lease_id` is what makes the audit trail useful for CA calls without ever
touching the secret. `ctx.record("credential.resolved", ..., lease_id=cred.lease_id)`
stores a value that's safe to log, safe to search on, safe to correlate across
requests — because it identifies *the checkout event*, not the secret's
contents. If a real vault audit is ever consulted to answer "was this lease
used by the right caller," `lease_id` is the join key.

### 2. It must be explicitly given back

A PAT and a cached OAuth token just... exist. Nothing in the system needs to be
told "I'm done with this token" — they're not checked out from anywhere.

A vault lease is checked out. If nom-py never tells the vault it's done, the
vault has no way to know the credential is no longer in active use — from the
vault's perspective, that lease could still be legitimately in use, so it sits
active until its own TTL eventually expires it. Every second in between is a
live, valid credential that isn't under nom-py's control anymore even though
nom-py has already finished using it. Phase 6 treats that gap as a bug: the
dispatcher must release every credential it checks out, deterministically, the
moment it's done with the call — success or failure.

That's why `EnterpriseCAProvider` is the only provider to override `release()`,
and why the dispatcher wraps the forward call in `try/finally`:

```python
try:
    ...  # forward to upstream (idempotency-wrapped if mutating)
finally:
    await provider.release(cred)
```

For `pat`/`oauth`/`cli`, `release()` is inherited as a no-op — calling it costs
nothing. For `ca`, it's the difference between a lease that's returned to the
vault the instant the call finishes and a lease that sits open until a TTL
eventually cleans it up. The `finally` makes this unconditional: whether the
upstream call succeeds, returns an error, or the connection itself blows up,
`provider.release(cred)` still runs.

**In one line:** PAT/OAuth/CLI are "get me a token" — CA is "check out a
credential, use it, and prove you checked it back in." The dispatcher's
`try/finally` exists specifically to make that checkout/return cycle
unconditional, and it costs the other three providers nothing to also go
through it.

---

## Request flow — the security-critical order

`MCPDispatcher._handle_tools_call()` runs these steps, in this exact order, for
every `tools/call`:

```
1. route, original_name = server_registry.resolve(exposed_name)
   └─ unknown/unnamespaced tool → -32602, nothing else runs

2. policy.evaluate_tool_call(principal, original_name, ctx)
   └─ denied → return policy error. providers.for_upstream() is NEVER called.

3. provider = providers.for_upstream(route)
   └─ unknown auth_mode → ConfigError → -32000

4. cred = await provider.get_upstream_credentials(principal, route)
   └─ raises ANY exception → -32000. upstream.forward() is NEVER called.

5. ctx.record("credential.resolved", provider=..., upstream=..., lease_id=cred.lease_id)
   └─ never cred.headers, never the secret

6. try: await upstream.forward(route.url, forward_msg, headers=cred.headers, ctx=ctx)
   finally: await provider.release(cred)
```

Steps 1–5 run identically for read-only and mutating tools. Only step 6
branches on `rule.get("mutating")`: mutating tools additionally acquire the
per-key idempotency lock and check/populate the idempotency cache *inside* the
`try`, so a cached-hit still triggers `provider.release()` in the `finally` —
the credential was resolved for this call regardless of whether the upstream
was actually reached.

### Why this exact ordering matters

- **Routing before policy** — resolving which upstream owns a tool is a pure
  lookup, not a security decision. It has to happen first because policy rules
  are keyed on the tool's original (un-namespaced) name, which routing is what
  produces.
- **Policy before provider lookup, before credential resolution** — this is the
  core invariant. A user who isn't allowed to call a tool must never cause
  nom-py to hit a secret store, mint an OAuth token, impersonate a service
  account, or lease a vault credential. Every one of those has a cost (API
  quota, audit noise in the *external* system, in CA's case an actual
  outstanding lease) that a denied call has no business incurring.
- **Fail closed on credential resolution** — nom-py must never forward a tool
  call to an upstream without a credential attached. There is deliberately no
  fallback path, no "call anyway without auth," no default token. An exception
  here is terminal for the request.
- **Audit records the reference, not the secret** — this is enforced by what
  the dispatcher chooses to pass to `ctx.record()`, not by any redaction logic
  downstream. `cred.headers` is never handed to `ctx.record()`, so the secret
  physically cannot end up in the audit trail — there's no filtering to get
  wrong later.
- **Release is unconditional** — a `try/finally` around the forward, not a
  bare call after it, so a released lease is guaranteed even when the upstream
  itself fails.

---

## Audit safety: `lease_id` in, never the secret

The one line the dispatcher emits for every resolved credential:

```python
ctx.record(
    "credential.resolved",
    provider=type(provider).__name__,
    upstream=route.name,
    lease_id=cred.lease_id,
)
```

For `pat`/`oauth`/`cli` calls, `lease_id` is `None` — those providers never
issue one, so the audit line simply confirms which provider ran and which
upstream it ran for. For `ca` calls, `lease_id` is the vault's checkout
reference. In no case does `cred.headers` — which is where the actual bearer
token or vault secret lives — ever reach `ctx.record()`.

[`tests/test_dispatcher_auth.py::test_secret_never_appears_in_audit_record_only_lease_id_does`](../tests/test_dispatcher_auth.py)
proves this isn't just "we didn't happen to log it" — it serializes the entire
`ctx.events` list to JSON and asserts the raw vault secret string is nowhere in
that blob, while the `lease_id` is present.

---

## What the test suite proves

| Test file | What it demonstrates |
|---|---|
| `tests/test_provider_registry.py` | Each `auth_mode` (`pat`/`oauth`/`cli`/`ca`) resolves to its correct provider class; an unregistered `auth_mode` raises `ConfigError` — fail closed, not a silent default |
| `tests/test_providers.py` | `GitHubPATProvider` returns `Authorization: Bearer <pat>` from the fake store; `GoogleOAuthProvider` mints once and reuses the cached token on a second call within TTL (fake endpoint hit exactly once); `GCPCLIProvider` returns an impersonated-token header; `EnterpriseCAProvider` returns a header + `lease_id`, and `release()` causes the fake vault to record the lease as invalidated |
| `tests/test_dispatcher_auth.py` | **Policy before credentials** — a denied tool never causes a spy provider's `get_upstream_credentials` to be called. **Fail closed** — a provider that raises means the dispatcher errors out and the upstream is never called. **Secret never logged** — the serialized audit record contains the `lease_id` but the raw vault secret string appears nowhere in it. **Lease released** — a successful CA call invalidates its lease in the fake vault, and a call where the upstream itself fails still releases the lease via the `finally`. **Correct header reaches upstream** — a fake upstream captures the request headers it received and they match exactly what the provider produced. **Un-namespacing** — calling `github__list_repos` results in the upstream receiving tool name `list_repos` |
| `tests/test_dispatcher_idempotency.py` | Pre-existing idempotency behavior (concurrent identical mutating calls serialize to one upstream call) still holds after the dispatcher was rewritten to route through `ServerRegistry` + `ProviderRegistry` |

Run everything:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v -p no:debugging
```

---

## What Phase 6 did NOT do

- **No real external calls.** Every provider is backed by an in-process fake
  (`FakeSecretStore`, `FakeOAuthTokenEndpoint`, `FakeTokenMinter`,
  `FakeVaultClient`). The `# REAL:` comments mark every swap point; none of
  them have been exercised against a live GitHub, Google, GCP, or enterprise
  vault API.
- **No refresh-token acquisition flow.** `GoogleOAuthProvider` assumes a
  refresh token already exists per user; the initial OAuth consent flow that
  would produce one is out of scope.
- **No credential rotation or revocation triggers** beyond the CA lease
  release path — there's no mechanism yet for, say, force-invalidating a PAT
  mid-flight if a user's access is revoked.
- **No multi-region / multi-vault topology** — `EnterpriseCAProvider` talks to
  a single `FakeVaultClient` instance; a real deployment might need
  vault-per-region or vault-per-environment routing.

---

## Phase summary

| Layer | Phase | Status |
|---|---|---|
| HTTP + routing scaffold | 1 | ✅ |
| MCP forwarding pipeline | 2 | ✅ |
| Token auth + policy enforcement | 3 | ✅ |
| Audit stream + idempotency + revert metadata | 4 | ✅ |
| stdio bridge + Claude Desktop integration | 5 | ✅ |
| Outbound credentials — AuthProvider layer (pat/oauth/cli/ca) | 6 | ✅ |
