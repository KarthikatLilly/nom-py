"""
MCP HTTP route — delegates all logic to the MCPDispatcher.
"""
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.mcp.dispatcher import MCPDispatcher
from app.mcp.upstream import UpstreamClient

router = APIRouter()

_upstream = UpstreamClient(endpoint=settings.upstream_endpoint)
_dispatcher = MCPDispatcher(upstream=_upstream)


class MCPRequest(BaseModel):
    """Loose model — MCP is JSON-RPC so we accept any extra fields."""
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


@router.post("/mcp", summary="MCP JSON-RPC entrypoint")
async def mcp_entry(body: MCPRequest) -> dict[str, Any]:
    return await _dispatcher.handle(body.model_dump(exclude_none=True))