"""
Token-based authentication.

Extracts tokens from:
- Authorization: Bearer <token> header
- JSON body: {"token": "..."}
- Query param: ?token=...

Validates against policy.yaml tokens.
"""
from typing import Any

from fastapi import Request

from app.auth.models import Principal
from app.config import settings


class AuthError(Exception):
    """Raised when authentication fails."""
    def __init__(self, message: str, code: int = -32001):
        self.message = message
        self.code = code
        super().__init__(message)


async def extract_token(request: Request, body: dict[str, Any], ctx=None) -> str | None:
    """Try 3 sources for the token, in order of preference."""
    # 1. Authorization header
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        if ctx is not None:
            ctx.record("auth.extract", source="header", found=True)
        return auth_header[7:].strip()

    # 2. JSON body
    if isinstance(body, dict) and "token" in body:
        if ctx is not None:
            ctx.record("auth.extract", source="body", found=True)
        return str(body["token"])

    # 3. Query param
    if "token" in request.query_params:
        if ctx is not None:
            ctx.record("auth.extract", source="query_param", found=True)
        return request.query_params["token"]

    if ctx is not None:
        ctx.record("auth.extract", source=None, found=False)
    return None


async def authenticate(request: Request, body: dict[str, Any], ctx=None) -> Principal:
    """
    Authenticate the request and return a Principal.
    Raises AuthError if authentication fails.
    """
    if not settings.auth_enabled:
        # Auth disabled — return a permissive anonymous principal
        return Principal(user_id="anonymous", groups=["*"])

    token = await extract_token(request, body, ctx)
    if not token:
        raise AuthError("Missing token", code=-32001)

    # Admin token is a first-class principal — not in the tokens table
    if token == settings.admin_token:
        if ctx is not None:
            ctx.record("auth.lookup", token_hint=token[:6] + "\u2026", result="admin", user_id="admin")
        return Principal(user_id="admin", groups=["admin"], token=token)

    token_info = settings.tokens.get(token)
    if not token_info:
        if ctx is not None:
            ctx.record("auth.lookup", token_hint=token[:6] + "\u2026", result="invalid")
        raise AuthError("Invalid token", code=-32001)

    principal = Principal(
        user_id=token_info.get("user_id", "unknown"),
        groups=token_info.get("groups", []),
        token=token,
    )
    if ctx is not None:
        ctx.record(
            "auth.lookup",
            token_hint=token[:6] + "\u2026",
            result="ok",
            user_id=principal.user_id,
        )
    return principal