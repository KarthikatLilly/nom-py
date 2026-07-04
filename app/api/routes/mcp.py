"""
MCP HTTP route — delegates all logic to the MCPDispatcher.
"""
from fastapi import APIRouter, Request

from app.config import settings
from app.mcp.dispatcher import MCPDispatcher
from app.mcp.upstream import UpstreamClient

router = APIRouter()

_upstream = UpstreamClient(endpoint=settings.upstream_endpoint)
_dispatcher = MCPDispatcher(upstream=_upstream)


@router.post("/mcp")
async def mcp_entry(request: Request):
    body = await request.json()
    return await _dispatcher.handle(body)