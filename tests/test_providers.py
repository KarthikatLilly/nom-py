"""
Individual AuthProvider behavior against their fake backing systems: header
shape, token-caching behavior, and lease lifecycle.
"""
import pytest

from app.auth.models import Principal
from app.auth.providers.ca import EnterpriseCAProvider
from app.auth.providers.cli import GCPCLIProvider
from app.auth.providers.fakes import (
    FakeOAuthTokenEndpoint,
    FakeSecretStore,
    FakeTokenMinter,
    FakeVaultClient,
)
from app.auth.providers.oauth import GoogleOAuthProvider
from app.auth.providers.pat import GitHubPATProvider
from app.mcp.server_registry import ServerConfig

ALICE = Principal(user_id="alice", groups=["developers"])


def _server(**kwargs) -> ServerConfig:
    return ServerConfig(name="s", url="http://fake/mcp", namespace="s", auth_mode="x", **kwargs)


@pytest.mark.asyncio
async def test_pat_provider_returns_bearer_from_fake_store():
    store = FakeSecretStore({"alice": "ghp_alice_token"})
    provider = GitHubPATProvider(store)

    cred = await provider.get_upstream_credentials(ALICE, _server())

    assert cred.headers["Authorization"] == "Bearer ghp_alice_token"


@pytest.mark.asyncio
async def test_oauth_provider_caches_token_within_ttl():
    endpoint = FakeOAuthTokenEndpoint()
    provider = GoogleOAuthProvider(endpoint)

    first = await provider.get_upstream_credentials(ALICE, _server())
    second = await provider.get_upstream_credentials(ALICE, _server())

    assert endpoint.calls == 1  # second call reused the cached token
    assert first.headers == second.headers


@pytest.mark.asyncio
async def test_cli_provider_returns_impersonated_token():
    minter = FakeTokenMinter()
    provider = GCPCLIProvider(minter)
    server = _server(service_account="nom-runner@example-project.iam.gserviceaccount.com")

    cred = await provider.get_upstream_credentials(ALICE, server)

    assert minter.calls == 1
    assert "nom-runner@example-project.iam.gserviceaccount.com" in cred.headers["Authorization"]


@pytest.mark.asyncio
async def test_ca_provider_returns_lease_and_releases_on_vault():
    vault = FakeVaultClient()
    provider = EnterpriseCAProvider(vault)
    server = _server(vault_safe="MCP-Internal-CA")

    cred = await provider.get_upstream_credentials(ALICE, server)

    assert "Authorization" in cred.headers
    assert cred.lease_id is not None
    assert vault.is_invalidated(cred.lease_id) is False

    await provider.release(cred)

    assert vault.is_invalidated(cred.lease_id) is True
