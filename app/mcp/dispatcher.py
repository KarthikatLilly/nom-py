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

logger = logging.getLogger(__name__)


class MCPDispatcher:
    def __init__(self, upstream: UpstreamClient, policy: PolicyEngine):
        self.upstream = upstream
        self.policy = policy

    async def handle(
        self, msg: dict[str, Any], principal: Principal
    ) -> dict[str, Any]:
        method = msg.get("method")
        msg_id = msg.get("id")

        logger.info(
            "MCP request: method=%s id=%s user=%s",
            method, msg_id, principal.user_id,
        )

        if method == "initialize":
            return await self._handle_initialize(msg)

        if method == "tools/list":
            return await self._handle_tools_list(msg, principal)

        if method == "tools/call":
            return await self._handle_tools_call(msg, principal)

        return self._error(msg_id, -32601, f"Method not supported: {method}")

    async def _handle_initialize(self, msg: dict[str, Any]) -> dict[str, Any]:
        upstream_result = await self.upstream.forward(msg)
        if "result" in upstream_result:
            upstream_result["result"]["serverInfo"] = {
                "name": "nom-py",
                "version": "0.3.0",
            }
        return upstream_result

    async def _handle_tools_list(
        self, msg: dict[str, Any], principal: Principal
    ) -> dict[str, Any]:
        upstream_result = await self.upstream.forward(msg)
        if "result" in upstream_result and "tools" in upstream_result["result"]:
            all_tools = upstream_result["result"]["tools"]
            filtered = self.policy.filter_tools_list(principal, all_tools)
            upstream_result["result"]["tools"] = filtered
        return upstream_result

    async def _handle_tools_call(
        self, msg: dict[str, Any], principal: Principal
    ) -> dict[str, Any]:
        params = msg.get("params", {}) or {}
        tool_name = params.get("name", "")

        try:
            self.policy.evaluate_tool_call(principal, tool_name)
        except PolicyDenied as e:
            return self._error(msg.get("id"), e.code, str(e))

        return await self.upstream.forward(msg)

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }