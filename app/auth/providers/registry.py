"""
ProviderRegistry — dict lookup from a server's auth_mode to its AuthProvider.
Unknown auth_mode fails closed (raises ConfigError) rather than silently
falling through to some default credential path.
"""
from app.auth.providers.base import AuthProvider, ConfigError
from app.auth.providers.ca import EnterpriseCAProvider
from app.auth.providers.cli import GCPCLIProvider
from app.auth.providers.oauth import GoogleOAuthProvider
from app.auth.providers.pat import GitHubPATProvider


class ProviderRegistry:
    def __init__(self, providers: dict[str, AuthProvider]):
        self._providers = providers

    def for_upstream(self, upstream) -> AuthProvider:
        try:
            return self._providers[upstream.auth_mode]
        except KeyError:
            raise ConfigError(f"No AuthProvider registered for auth_mode '{upstream.auth_mode}'")


def default_registry() -> ProviderRegistry:
    """Wires each auth_mode to its provider, backed by fake I/O for this demo."""
    return ProviderRegistry({
        "pat": GitHubPATProvider(),
        "oauth": GoogleOAuthProvider(),
        "cli": GCPCLIProvider(),
        "ca": EnterpriseCAProvider(),
    })
