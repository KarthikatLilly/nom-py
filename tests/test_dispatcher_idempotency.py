"""
Regression test for the mutating tool-call path in MCPDispatcher.

Proves that IdempotencyStore.lock_for exists and produces a usable lock,
and that concurrent identical mutating calls are serialised so the
upstream is only invoked once and the second call gets the cached result.
"""
import asyncio

import pytest

from app.auth.models import Principal
from app.mcp.dispatcher import MCPDispatcher
from app.policy.engine import PolicyEngine


class FakeUpstream:
    def __init__(self):
        self.calls = 0

    async def forward(self, msg, ctx=None):
        self.calls += 1
        await asyncio.sleep(0.05)  # widen the race window
        return {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"ok": True}}


class FakePolicy(PolicyEngine):
    def __init__(self):
        self.rules = {"create_bucket": {"allow": True, "mutating": True}}


@pytest.mark.asyncio
async def test_concurrent_mutating_calls_are_serialised():
    upstream = FakeUpstream()
    dispatcher = MCPDispatcher(upstream=upstream, policy=FakePolicy())
    principal = Principal(user_id="u1", groups=[])

    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "create_bucket", "arguments": {"name": "b1"}},
    }

    results = await asyncio.gather(
        dispatcher.handle(msg, principal),
        dispatcher.handle(msg, principal),
    )

    assert upstream.calls == 1  # second call hit the idempotency cache
    assert results[0] == results[1]
