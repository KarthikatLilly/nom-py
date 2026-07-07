"""
MCP Dispatcher — the core routing brain of nom-py.

Handles JSON-RPC methods:
- initialize
- tools/list
- tools/call

Enforces auth and policy before forwarding to the upstream.
"""
import logging
from typing import Any

from app.auth.models import Principal
from app.mcp.upstream import UpstreamClient
from app.policy.engine import PolicyEngine
from app.policy.errors import PolicyDenied
from app.safety.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)


class MCPDispatcher:
    def __init__(self, upstream: UpstreamClient, policy: PolicyEngine, idempotency: IdempotencyStore | None = None):
        self.upstream = upstream
        self.policy = policy
        self.idempotency = idempotency or IdempotencyStore()

    async def handle(
        self, msg: dict[str, Any], principal: Principal, ctx=None
    ) -> dict[str, Any] | None:
        method = msg.get("method")
        msg_id = msg.get("id")
        is_notification = msg_id is None

        logger.info(
            "MCP request: method=%s id=%s user=%s",
            method, msg_id, principal.user_id,
        )

        if method == "initialize":
            result = await self._handle_initialize(msg, ctx)
        elif method == "tools/list":
            result = await self._handle_tools_list(msg, principal, ctx)
        elif method == "tools/call":
            result = await self._handle_tools_call(msg, principal, ctx)
        elif is_notification:
            # Notifications are fire-and-forget lifecycle signals — log and drop
            logger.info("Notification received: %s (ignored)", method)
            if ctx is not None:
                ctx.record("notification.received", method=method)
            result = None
        else:
            result = self._error(msg_id, -32601, f"Method not supported: {method}")

        if ctx is not None:
            if is_notification:
                outcome = "notification"
            elif result and "error" in result:
                outcome = "error"
            else:
                outcome = "ok"
            ctx.record("dispatch.complete", outcome=outcome)
        return result

    async def _handle_initialize(self, msg: dict[str, Any], ctx=None) -> dict[str, Any]:
        upstream_result = await self.upstream.forward(msg, ctx)
        if "result" in upstream_result:
            upstream_result["result"]["serverInfo"] = {
                "name": "nom-py",
                "version": "0.4.0",
            }
            # Guarantee capabilities.tools is present even if upstream omits it
            if "capabilities" not in upstream_result["result"]:
                upstream_result["result"]["capabilities"] = {"tools": {}}
        return upstream_result

    async def _handle_tools_list(
        self, msg: dict[str, Any], principal: Principal, ctx=None
    ) -> dict[str, Any]:
        upstream_result = await self.upstream.forward(msg, ctx)
        if "result" in upstream_result and "tools" in upstream_result["result"]:
            all_tools = upstream_result["result"]["tools"]
            filtered = self.policy.filter_tools_list(principal, all_tools)
            upstream_result["result"]["tools"] = filtered
        return upstream_result

    async def _handle_tools_call(
        self, msg: dict[str, Any], principal: Principal, ctx=None
    ) -> dict[str, Any]:
        params = msg.get("params", {}) or {}
        tool_name = params.get("name", "")
        args = params.get("arguments", {}) or {}

        try:
            self.policy.evaluate_tool_call(principal, tool_name, ctx)
        except PolicyDenied as e:
            return self._error(msg.get("id"), e.code, str(e))

        rule = self.policy.rules.get(tool_name, {})

        if not rule.get("mutating"):
            # Read-only tool — forward directly, no idempotency overhead
            return await self.upstream.forward(msg, ctx)

        # Mutating tool — serialise concurrent identical calls under a per-key lock
        idempotency_key = self.idempotency.key_for(
            principal.user_id,
            tool_name,
            args,
            params.get("idempotency_key"),
        )
        async with self.idempotency.lock_for(idempotency_key):
            cached = self.idempotency.get(idempotency_key)
            if cached:
                if ctx is not None:
                    ctx.record("idempotency.hit", key=idempotency_key)
                return cached
            if ctx is not None:
                ctx.record("idempotency.miss", key=idempotency_key)

            result = await self.upstream.forward(msg, ctx)

            # Only cache confirmed successes — never persist upstream errors
            if "error" not in result:
                self.idempotency.put(idempotency_key, result)

        return result

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }