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


async def extract_token(request: Request, body: dict[str, Any]) -> str | None:
    """Try 3 sources for the token, in order of preference."""
    # 1. Authorization header
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    # 2. JSON body
    if isinstance(body, dict) and "token" in body:
        return str(body["token"])

    # 3. Query param
    if "token" in request.query_params:
        return request.query_params["token"]

    return None


async def authenticate(request: Request, body: dict[str, Any]) -> Principal:
    """
    Authenticate the request and return a Principal.
    Raises AuthError if authentication fails.
    """
    if not settings.auth_enabled:
        # Auth disabled — return a permissive anonymous principal
        return Principal(user_id="anonymous", groups=["*"])

    token = await extract_token(request, body)
    if not token:
        raise AuthError("Missing token", code=-32001)

    token_info = settings.tokens.get(token)
    if not token_info:
        raise AuthError("Invalid token", code=-32001)

    return Principal(
        user_id=token_info.get("user_id", "unknown"),
        groups=token_info.get("groups", []),
        token=token,
    )