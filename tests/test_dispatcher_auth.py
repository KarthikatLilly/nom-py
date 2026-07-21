"""
Security-behavior tests for MCPDispatcher.tools/call outbound-credential
handling. These assert the ORDER and FAIL-CLOSED guarantees are real, not
just that the happy path works:

- policy runs before any credential provider is touched
- a credential failure never reaches the upstream
- secrets never leak into the audit trail (only the lease_id does)
- leases are released whether the call succeeds or fails
- the header the provider produced is exactly what the upstream receives
- namespaced tool names are stripped before reaching the upstream
"""
import json

import pytest

from app.auth.models import Principal
from app.auth.providers.base import AuthProvider, UpstreamCredential
from app.auth.providers.ca import EnterpriseCAProvider
from app.auth.providers.fakes import FakeSecretStore, FakeVaultClient
from app.auth.providers.pat import GitHubPATProvider
from app.auth.providers.registry import ProviderRegistry
from app.mcp.dispatcher import MCPDispatcher
from app.mcp.server_registry import ServerConfig, ServerRegistry
from app.observability.context import RequestContext
from app.policy.engine import PolicyEngine

ALICE = Principal(user_id="alice", groups=["developers"])


class FakePolicy(PolicyEngine):
    def __init__(self, rules: dict):
        self.rules = rules


class FakeUpstream:
    """Captures every forward() call so tests can assert on url/msg/headers."""

    def __init__(self, response_factory=None):
        self.calls: list[dict] = []
        self._response_factory = response_factory

    async def forward(self, url, msg, headers=None, ctx=None):
        self.calls.append({"url": url, "msg": msg, "headers": headers})
        if self._response_factory is not None:
            return self._response_factory(msg)
        return {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"ok": True}}


class RaisingUpstream:
    """Simulates a hard upstream failure (connection reset, etc.) to prove
    the credential is still released via `finally` even when forward blows up."""

    async def forward(self, url, msg, headers=None, ctx=None):
        raise RuntimeError("connection reset")


class SpyProvider(AuthProvider):
    """Counts calls so a test can assert it was NEVER invoked."""

    def __init__(self):
        self.calls = 0

    async def get_upstream_credentials(self, principal, upstream):
        self.calls += 1
        return UpstreamCredential(headers={"Authorization": "Bearer spy"})


class RaisingProvider(AuthProvider):
    async def get_upstream_credentials(self, principal, upstream):
        raise RuntimeError("vault unreachable")


def _servers(**configs: ServerConfig) -> ServerRegistry:
    return ServerRegistry(configs)


def _msg(tool: str, args: dict | None = None, msg_id=1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    }


@pytest.mark.asyncio
async def test_policy_evaluated_before_credentials_are_resolved():
    """A globally-denied tool must short-circuit before touching any provider."""
    spy = SpyProvider()
    servers = _servers(github=ServerConfig(name="github", url="http://fake/mcp", namespace="github", auth_mode="pat"))
    policy = FakePolicy({"delete_user": {"allow": False, "reason": "destructive"}})
    dispatcher = MCPDispatcher(
        upstream=FakeUpstream(),
        policy=policy,
        servers=servers,
        providers=ProviderRegistry({"pat": spy}),
    )

    result = await dispatcher.handle(_msg("github__delete_user"), ALICE)

    assert "error" in result
    assert spy.calls == 0  # provider must never be touched for a denied call


@pytest.mark.asyncio
async def test_credential_failure_fails_closed_upstream_never_called():
    """If credential resolution raises, the dispatcher must error out and
    must NEVER forward the call to the upstream unauthenticated."""
    upstream = FakeUpstream()
    servers = _servers(github=ServerConfig(name="github", url="http://fake/mcp", namespace="github", auth_mode="pat"))
    policy = FakePolicy({"get_weather": {"allow": True, "mutating": False}})
    dispatcher = MCPDispatcher(
        upstream=upstream,
        policy=policy,
        servers=servers,
        providers=ProviderRegistry({"pat": RaisingProvider()}),
    )

    result = await dispatcher.handle(_msg("github__get_weather"), ALICE)

    assert "error" in result
    assert upstream.calls == []  # never reached


@pytest.mark.asyncio
async def test_secret_never_appears_in_audit_record_only_lease_id_does():
    vault = FakeVaultClient()
    upstream = FakeUpstream()
    servers = _servers(internal=ServerConfig(
        name="internal", url="http://fake/mcp", namespace="internal", auth_mode="ca", vault_safe="MCP-Internal-CA",
    ))
    policy = FakePolicy({"get_weather": {"allow": True, "mutating": False}})
    dispatcher = MCPDispatcher(
        upstream=upstream,
        policy=policy,
        servers=servers,
        providers=ProviderRegistry({"ca": EnterpriseCAProvider(vault)}),
    )
    ctx = RequestContext(method="tools/call")

    await dispatcher.handle(_msg("internal__get_weather"), ALICE, ctx)

    lease_events = [e for e in ctx.events if e["stage"] == "credential.resolved"]
    assert len(lease_events) == 1
    lease_id = lease_events[0]["lease_id"]
    assert lease_id is not None

    secret = vault._leases[lease_id].secret
    serialized = json.dumps(ctx.events)

    assert lease_id in serialized
    assert secret not in serialized  # the raw secret must never be audited


@pytest.mark.asyncio
async def test_ca_lease_invalidated_after_successful_call():
    vault = FakeVaultClient()
    servers = _servers(internal=ServerConfig(
        name="internal", url="http://fake/mcp", namespace="internal", auth_mode="ca", vault_safe="MCP-Internal-CA",
    ))
    policy = FakePolicy({"get_weather": {"allow": True, "mutating": False}})
    dispatcher = MCPDispatcher(
        upstream=FakeUpstream(),
        policy=policy,
        servers=servers,
        providers=ProviderRegistry({"ca": EnterpriseCAProvider(vault)}),
    )
    ctx = RequestContext(method="tools/call")

    await dispatcher.handle(_msg("internal__get_weather"), ALICE, ctx)

    lease_id = next(e for e in ctx.events if e["stage"] == "credential.resolved")["lease_id"]
    assert vault.is_invalidated(lease_id) is True


@pytest.mark.asyncio
async def test_ca_lease_invalidated_via_finally_even_when_upstream_call_fails():
    vault = FakeVaultClient()
    servers = _servers(internal=ServerConfig(
        name="internal", url="http://fake/mcp", namespace="internal", auth_mode="ca", vault_safe="MCP-Internal-CA",
    ))
    policy = FakePolicy({"get_weather": {"allow": True, "mutating": False}})
    dispatcher = MCPDispatcher(
        upstream=RaisingUpstream(),
        policy=policy,
        servers=servers,
        providers=ProviderRegistry({"ca": EnterpriseCAProvider(vault)}),
    )
    ctx = RequestContext(method="tools/call")

    with pytest.raises(RuntimeError):
        await dispatcher.handle(_msg("internal__get_weather"), ALICE, ctx)

    lease_id = next(e for e in ctx.events if e["stage"] == "credential.resolved")["lease_id"]
    assert vault.is_invalidated(lease_id) is True  # released even though the call blew up


@pytest.mark.asyncio
async def test_upstream_receives_exact_header_the_provider_produced():
    store = FakeSecretStore({"alice": "ghp_alice_specific_token"})
    upstream = FakeUpstream()
    servers = _servers(github=ServerConfig(name="github", url="http://fake-upstream/mcp", namespace="github", auth_mode="pat"))
    policy = FakePolicy({"get_weather": {"allow": True, "mutating": False}})
    dispatcher = MCPDispatcher(
        upstream=upstream,
        policy=policy,
        servers=servers,
        providers=ProviderRegistry({"pat": GitHubPATProvider(store)}),
    )

    await dispatcher.handle(_msg("github__get_weather"), ALICE)

    assert len(upstream.calls) == 1
    assert upstream.calls[0]["headers"]["Authorization"] == "Bearer ghp_alice_specific_token"
    assert upstream.calls[0]["url"] == "http://fake-upstream/mcp"


@pytest.mark.asyncio
async def test_namespace_prefix_is_stripped_before_reaching_upstream():
    upstream = FakeUpstream()
    servers = _servers(github=ServerConfig(name="github", url="http://fake/mcp", namespace="github", auth_mode="pat"))
    policy = FakePolicy({"list_repos": {"allow": True, "mutating": False}})
    dispatcher = MCPDispatcher(
        upstream=upstream,
        policy=policy,
        servers=servers,
        providers=ProviderRegistry({"pat": GitHubPATProvider()}),
    )

    await dispatcher.handle(_msg("github__list_repos"), ALICE)

    assert len(upstream.calls) == 1
    assert upstream.calls[0]["msg"]["params"]["name"] == "list_repos"
