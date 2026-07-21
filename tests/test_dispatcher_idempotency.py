"""
Regression test for the mutating tool-call path in MCPDispatcher.

Proves that IdempotencyStore.lock_for exists and produces a usable lock,
and that concurrent identical mutating calls are serialised so the
upstream is only invoked once and the second call gets the cached result.
"""
import asyncio

import pytest

from app.auth.models import Principal
from app.auth.providers.pat import GitHubPATProvider
from app.auth.providers.registry import ProviderRegistry
from app.mcp.dispatcher import MCPDispatcher
from app.mcp.server_registry import ServerConfig, ServerRegistry
from app.policy.engine import PolicyEngine


class FakeUpstream:
    def __init__(self):
        self.calls = 0

    async def forward(self, url, msg, headers=None, ctx=None):
        self.calls += 1
        await asyncio.sleep(0.05)  # widen the race window
        return {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"ok": True}}


class FakePolicy(PolicyEngine):
    def __init__(self):
        self.rules = {"create_bucket": {"allow": True, "mutating": True}}


@pytest.mark.asyncio
async def test_concurrent_mutating_calls_are_serialised():
    upstream = FakeUpstream()
    servers = ServerRegistry({
        "github": ServerConfig(name="github", url="http://fake/mcp", namespace="github", auth_mode="pat"),
    })
    dispatcher = MCPDispatcher(
        upstream=upstream,
        policy=FakePolicy(),
        servers=servers,
        providers=ProviderRegistry({"pat": GitHubPATProvider()}),
    )
    principal = Principal(user_id="alice", groups=[])

    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "github__create_bucket", "arguments": {"name": "b1"}},
    }

    results = await asyncio.gather(
        dispatcher.handle(msg, principal),
        dispatcher.handle(msg, principal),
    )

    assert upstream.calls == 1  # second call hit the idempotency cache
    assert results[0] == results[1]
