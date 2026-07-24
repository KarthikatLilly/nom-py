# Authentication Abstraction and Privileged Identity Management in NOM

*A design overview of how NOM should authenticate a single user across many upstream MCP servers that each use a different credential model (GitHub PAT, Google OAuth, GCP CLI, and internal CA accounts), and how it handles privileged access safely.*

---

## 1. Executive summary

NOM is a governed MCP gateway. Agents connect to one endpoint, and NOM forwards their tool calls to many upstream tool servers after applying authentication, authorization, and auditing in one place.

The problem it solves is not routing. Routing is easy. The hard problem is that every upstream authenticates differently, while the person behind the request is always the same one user.

```
Many MCP servers
Many authentication models
One user
```

Different upstreams expect different credentials:

```
GitHub MCP    -> PAT
Google MCP    -> OAuth
GCP MCP       -> CLI / impersonation
Internal MCP  -> CA account (vaulted)
```

Without a gateway, the client has to carry all of that itself:

```
Client
 |-- PAT
 |-- OAuth
 |-- CLI auth
 |-- Enterprise (CA) auth
```

With NOM, the client carries none of it:

```
Client
   |
   v
  NOM   (auth, policy, credentials, audit)
   |
   v
Many MCP servers
```

The real work sits in four areas that have to hold across every upstream at once: identity, authorization, credential resolution, and auditability. This document explains how NOM should keep those four consistent without writing special-case code for each upstream, and why privileged CA accounts are the case that shapes the whole design.

---

## 2. The one idea that makes it simple: two separate questions

The insight that makes the whole design fall into place is that there are two authentication questions, not one. They look similar, so people blur them together. Keeping them apart is what keeps the code clean.

**Question 1: Who is calling NOM?**

This is the user proving who they are to NOM. NOM turns a bearer token into a `Principal` that carries the user and their groups.

```
Bearer token
   |
   v
Principal (user, groups)
```

Call this inbound identity. It already exists in the prototype and did not change.

**Question 2: How does NOM call the upstream on that user's behalf?**

This is a completely different question. Once a call is allowed, NOM still has to present the right credential to the upstream, and each upstream wants a different kind:

```
GitHub   -> PAT
Google   -> OAuth token
GCP      -> impersonated token
Internal -> CA lease
```

Call this outbound credential resolution.

Here is why this framing matters. PAT, OAuth, CLI, and CA look like four unrelated features. They are not. They are four answers to the same single question: *how do I produce the outbound credential for this call?* Once you see them that way, you stop building four features and start building one thing with four plug-ins. That one thing is the AuthProvider abstraction in Section 4.

| | Inbound identity | Outbound credential |
|---|---|---|
| Question | Who is calling NOM? | How does NOM call the upstream, as that user? |
| Result | `Principal` | `UpstreamCredential` |
| Lives in | token auth (Phases 1 to 5) | AuthProvider layer (Phase 6) |

---

## 3. Why CA accounts are the hard case

A normal account does everyday work like mail and internal tools. A CA account exists to do production access, cloud administration, infrastructure changes. Because the power is so much higher, enterprises wrap it in controls that ordinary accounts never need. Three of those controls drive the NOM design.

### Vaulting

The fear: what if the credential leaks?

If a privileged password lived in a config file or a chat message, it would sit there valid for months, and every copy is a place it can be stolen. Vaulting fixes this. The secret has one home, it is encrypted there, it rotates on a schedule, and it is handed out only briefly on request.

```
Vault
  |
Short-lived retrieval
  |
Rotation
```

### Rotation

A normal password is set once and used for months. A privileged credential changes automatically and often. Conceptually:

```
Vault
  |
Generate a new password
  |
Update the target system
  |
Store the new password
```

The result is the point of the whole exercise: old copies become useless. If someone saved yesterday's password, it no longer works today. That single property removes most of the value of a stolen privileged secret.

### Leases: the most important idea for NOM

This is the concept that shapes NOM's design more than any other.

A password is a permanent secret. A lease is a temporary right to use a secret. The difference sounds small and is not.

```
Vault
  |
Issue a credential
  |
Valid for a few minutes
  |
Expires automatically
```

It works like borrowing a library book. You check it out, you use it, you return it. You do not take it forever.

A lease is also a tracked record, not just a value. The vault remembers metadata about each checkout:

```
Lease ID
Requested by
Issued at
Expires at
Target system
```

For example:

```
Lease:        abc123
Requested by: karthikeya
Issued:       10:00
Expires:      10:05
```

The important detail: the audit trail stores the **lease ID**, never the password. This is exactly why NOM records `lease_id` instead of the secret. It is a reference that is safe to log, safe to search, and safe to correlate, because it identifies the checkout event and not the secret's contents.

### Just-in-time (JIT) access

The traditional model gives an engineer admin access and lets them keep it forever. That is a large, permanent attack surface for access that is used rarely.

The JIT model grants privilege only for as long as it is needed:

```
Need access?
  |
Request it
  |
Approved
  |
Temporary privilege
  |
Automatically removed
```

The security payoff is easy to see. Without JIT, one hundred engineers means one hundred permanent admins. With JIT, one hundred engineers might mean two active admins at this exact moment, and both of those grants disappear on their own shortly after. Nothing has to be cleaned up by hand.

Vaulting, rotation, leases, and JIT all point at the same conclusion. A privileged credential should never be held, never be permanent, and never be used without a record of who used it and why. That conclusion is what NOM's CA design implements.

---

## 4. The AuthProvider design

Every upstream declares which credential method it needs with a single field, `auth_mode`. NOM looks that up and gets back an object that knows how to produce the credential.

```
Server config
  |
auth_mode  ("pat" / "oauth" / "cli" / "ca")
  |
Provider registry  (a dictionary lookup)
  |
AuthProvider  (one interface)
```

The four implementations:

```
GitHubPATProvider       (static token, held in a secret store)
GoogleOAuthProvider     (short-lived token, refreshed and cached)
GCPCLIProvider          (impersonated service account, minted per call)
EnterpriseCAProvider    (vault lease, short-lived, returned after use)
```

### Why not if / else

The naive version puts a branch per upstream inside the request path:

```python
if github:   ...
elif oauth:  ...
elif gcp:    ...
```

That works for two upstreams and rots at four. It also mixes three unrelated concerns in one place: which upstream, which credential scheme, and whether the call is even allowed.

The clean version is a lookup table. `auth_mode` is a string, the registry is a dictionary, and the value is the provider to use. Dictionary lookup is fast (constant time on average), and, more importantly, adding a fifth credential type is one new class plus one new line in the registry. The dispatcher never changes. This is the scalability property directly: the cost of a new integration does not grow the core request path.

The dispatcher only ever talks to the AuthProvider interface. It has no knowledge of PATs, OAuth refresh, GCP impersonation, or vault leases. That knowledge lives entirely inside each provider.

---

## 5. The CA credential lifecycle in NOM

This is the strongest part of the design. It shows how identity, policy, approval, vaulting, leases, and audit come together in a single request.

```
User
  |
JWT identity
  |
Principal (user, groups)
  |
Policy check
  |
Need CA?
  |
Check entitlement
  |
Approval
  |
Vault issues a lease
  |
NOM uses the lease
  |
One upstream call
  |
Lease destroyed
  |
Audit event
```

Three properties make this safe.

**Policy runs before credentials.** NOM decides "is this allowed?" before it does anything to obtain a credential. A denied call never causes NOM to hit a secret store, mint a token, or open a vault lease. Getting this order backwards would mean handing out privileged power to requests you were about to refuse.

**The credential is short-lived and returned.** NOM does not store a CA secret. It leases one, uses it for exactly one call, and gives it back the moment the call finishes, whether the call succeeded or failed.

```
Vault
  |
Lease
  |
One call
  |
Destroy
```

**Identity is re-attached.** A CA account is shared, so on its own it cannot answer "which human did this?" NOM answers it. By binding the human `Principal` and an approval record to each use of the shared credential, NOM turns an anonymous privileged action into a named, auditable one.

### How this replaces the traditional PAM flow

The traditional path exposes the secret to a person:

```
User
  |
Gets the CA password
  |
Copies the CA password
  |
Uses the system
```

The problems are familiar: the password is exposed, auditing is weak, and attribution is hard because the account is shared.

The NOM path never exposes the secret to anyone:

```
User
  |
NOM
  |
Policy engine
  |
Approval
  |
Vault
  |
Short-lived lease
  |
Upstream MCP
  |
Audit
```

This is where NOM fits a PAM or vault system such as CyberArk together with JIT access. The vault holds and rotates the secret, JIT keeps the grant temporary, and NOM is the broker in the middle that enforces policy, records approval, uses the lease for one call, and writes the audit event. No human ever touches the credential.

---

## 6. What the prototype implements and validates

**This phase is a local demo in https://github.com/KarthikatLilly/nom-py .** No real GitHub, Google, GCP, or vault API is called. Each provider talks to an in-process fake, and every point where a real SDK call belongs is marked in the code with a `# REAL:` comment. The shape of the abstraction and the order of the security checks are built to be production representative. Only the input and output underneath is faked. This is a deliberate choice: it proves the design is correct and buildable, and it makes each real integration a small, isolated swap rather than a redesign.

Two earlier code-review concerns (a duplicate audit write, and a missing per-key idempotency lock) were checked and confirmed already resolved in the current code.

Phase 6 adds the outbound credential layer:

```
AuthProvider abstraction
Provider registry (dictionary lookup, fails closed on unknown mode)
PAT provider
OAuth provider
CLI provider
CA provider
Server registry with namespaced routing (github__list_repos -> list_repos)
```

The value of the design is not in the code volume, which is small. It is in the security properties that automated tests now prove hold for every provider through the same code path.

| Property | What the test shows |
|---|---|
| Policy before credentials | A denied tool never causes a provider to be touched at all |
| Fail closed | If credential resolution raises, the request errors and the upstream is never called |
| No secret leakage | The audit record contains the lease ID but never the raw secret |
| Lease released on success | After a normal CA call, the vault shows the lease invalidated |
| Lease released on failure | Even when the upstream call fails, the lease is still returned |
| Header integrity | The exact credential the provider produced is what reaches the upstream |
| Namespace isolation | `github__list_repos` reaches the upstream as `list_repos` |

---

## 7. Key takeaways and future work

Three ideas are worth carrying forward.

**Authentication, authorization, and credential resolution are three different things.** Knowing who someone is, deciding what they may do, and producing the credential to do it are separate problems. The prototype keeps them separate, which is why each can change without disturbing the others.

**Privileged access is a design problem, not a login problem.** CA accounts force vaulting, leases, approval, and auditing. A gateway that handles CA correctly handles the easier credential types as simpler cases of the same pattern.

**NOM's value is brokering, not storing.** The single sentence that captures the whole CA design:

> NOM's value is not that it stores privileged credentials. NOM's value is that it brokers short-lived privileged access while preserving human identity, policy enforcement, approval history, and auditability.

Or more briefly: NOM converts a shared privileged credential into a per-user, per-action, fully auditable event.

**Future work**, in the order it would make sense to build:

```
Real JWT identity from an enterprise IdP
Real OAuth (consent and refresh-token storage)
Real vault integration for CA leases
Multi-upstream registry with distinct real upstreams
Approval workflows for privileged and destructive actions
```

