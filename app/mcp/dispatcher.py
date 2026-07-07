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
    ) -> dict[str, Any]:
        method = msg.get("method")
        msg_id = msg.get("id")

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
        else:
            result = self._error(msg_id, -32601, f"Method not supported: {method}")

        if ctx is not None:
            ctx.record("dispatch.complete", outcome="error" if "error" in result else "ok")
        return result

    async def _handle_initialize(self, msg: dict[str, Any], ctx=None) -> dict[str, Any]:
        upstream_result = await self.upstream.forward(msg, ctx)
        if "result" in upstream_result:
            upstream_result["result"]["serverInfo"] = {
                "name": "nom-py",
                "version": "0.3.0",
            }
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
        idempotency_key = None

        if rule.get("mutating"):
            idempotency_key = self.idempotency.key_for(
                principal.user_id,
                tool_name,
                args,
                params.get("idempotency_key"),
            )
            cached = self.idempotency.get(idempotency_key)
            if cached:
                if ctx is not None:
                    ctx.record("idempotency.hit", key=idempotency_key)
                return cached
            if ctx is not None:
                ctx.record("idempotency.miss", key=idempotency_key)

        result = await self.upstream.forward(msg, ctx)

        if idempotency_key is not None:
            self.idempotency.put(idempotency_key, result)

        return result

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }