"""
MCP Dispatcher — the core routing brain of nom-py.

Handles JSON-RPC methods:
- initialize
- tools/list
- tools/call

Delegates upstream forwarding to app.mcp.upstream.
"""
import logging
from typing import Any

from app.mcp.upstream import UpstreamClient

logger = logging.getLogger(__name__)


class MCPDispatcher:
    def __init__(self, upstream: UpstreamClient):
        self.upstream = upstream

    async def handle(self, msg: dict[str, Any]) -> dict[str, Any]:
        method = msg.get("method")
        msg_id = msg.get("id")

        logger.info("MCP request received: method=%s id=%s", method, msg_id)

        if method == "initialize":
            return await self._handle_initialize(msg)

        if method == "tools/list":
            return await self._handle_tools_list(msg)

        if method == "tools/call":
            return await self._handle_tools_call(msg)

        return self._error(msg_id, -32601, f"Method not supported: {method}")

    async def _handle_initialize(self, msg: dict[str, Any]) -> dict[str, Any]:
        # nom-py speaks MCP to the client and forwards the handshake
        upstream_result = await self.upstream.forward(msg)

        # Optionally wrap or override serverInfo to identify as nom-py
        if "result" in upstream_result:
            upstream_result["result"]["serverInfo"] = {
                "name": "nom-py",
                "version": "0.2.0",
            }
        return upstream_result

    async def _handle_tools_list(self, msg: dict[str, Any]) -> dict[str, Any]:
        return await self.upstream.forward(msg)

    async def _handle_tools_call(self, msg: dict[str, Any]) -> dict[str, Any]:
        # Phase 3 will add policy check here BEFORE forwarding
        return await self.upstream.forward(msg)

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }