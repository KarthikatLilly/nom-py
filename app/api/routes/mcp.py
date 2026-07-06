"""
MCP HTTP route — delegates all logic to the MCPDispatcher.
"""
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.auth.token_auth import authenticate, AuthError
from app.config import settings
from app.mcp.dispatcher import MCPDispatcher
from app.mcp.upstream import UpstreamClient
from app.policy.engine import PolicyEngine

router = APIRouter()

_upstream = UpstreamClient(endpoint=settings.upstream_endpoint)
_policy = PolicyEngine()
_dispatcher = MCPDispatcher(upstream=_upstream, policy=_policy)


class MCPRequest(BaseModel):
    """Loose model — MCP is JSON-RPC so we accept any extra fields."""
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None
    token: str | None = None  # allow token in body too

    model_config = ConfigDict(extra="allow")


@router.post("/mcp", summary="MCP JSON-RPC entrypoint")
async def mcp_entry(body: MCPRequest, request: Request) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)

    # Skip auth for `initialize` — the client hasn't authenticated yet
    if payload.get("method") == "initialize":
        # Use a stub principal so dispatcher signature stays consistent
        from app.auth.models import Principal
        anonymous = Principal(user_id="anonymous", groups=[])
        return await _dispatcher.handle(payload, anonymous)

    try:
        principal = await authenticate(request, payload)
    except AuthError as e:
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "error": {"code": e.code, "message": e.message},
        }

    return await _dispatcher.handle(payload, principal)