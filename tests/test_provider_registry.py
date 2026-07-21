"""
ProviderRegistry — each auth_mode resolves to the right AuthProvider class,
and an unknown auth_mode fails closed rather than falling through to a
default credential path.
"""
import pytest

from app.auth.providers.base import ConfigError
from app.auth.providers.ca import EnterpriseCAProvider
from app.auth.providers.cli import GCPCLIProvider
from app.auth.providers.oauth import GoogleOAuthProvider
from app.auth.providers.pat import GitHubPATProvider
from app.auth.providers.registry import ProviderRegistry, default_registry
from app.mcp.server_registry import ServerConfig


def _server(auth_mode: str) -> ServerConfig:
    return ServerConfig(name="s", url="http://fake/mcp", namespace="s", auth_mode=auth_mode)


@pytest.mark.parametrize(
    "auth_mode,expected_cls",
    [
        ("pat", GitHubPATProvider),
        ("oauth", GoogleOAuthProvider),
        ("cli", GCPCLIProvider),
        ("ca", EnterpriseCAProvider),
    ],
)
def test_resolves_correct_provider_for_auth_mode(auth_mode, expected_cls):
    registry = default_registry()
    provider = registry.for_upstream(_server(auth_mode))
    assert isinstance(provider, expected_cls)


def test_unknown_auth_mode_fails_closed():
    registry = ProviderRegistry({"pat": GitHubPATProvider()})
    with pytest.raises(ConfigError):
        registry.for_upstream(_server("smartcard"))
