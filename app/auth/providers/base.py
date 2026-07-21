"""
AuthProvider — outbound credential resolution abstraction.

Distinguishes inbound identity (who is calling NOM — Principal, unchanged)
from outbound credentials (how NOM calls a given upstream as that user).
Each upstream's auth_mode maps to exactly one AuthProvider implementation;
the dispatcher never branches per-upstream, only through this interface.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.auth.models import Principal

if TYPE_CHECKING:
    from app.mcp.server_registry import ServerConfig


class ConfigError(Exception):
    """Invalid or missing routing/provider configuration — callers must fail closed."""


@dataclass
class UpstreamCredential:
    headers: dict[str, str]
    expires_at: float | None = None
    lease_id: str | None = None  # audit reference only — never the secret itself


class AuthProvider(ABC):
    @abstractmethod
    async def get_upstream_credentials(
        self, principal: Principal, upstream: "ServerConfig"
    ) -> UpstreamCredential:
        ...

    async def release(self, cred: UpstreamCredential) -> None:
        """Default no-op — override for providers that check out a lease/session."""
        return None
