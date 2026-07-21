"""
GitHubPATProvider — resolves a per-user GitHub personal access token from a
secret store. PATs are long-lived and static: no refresh cycle, no lease to
release.
"""
from app.auth.models import Principal
from app.auth.providers.base import AuthProvider, UpstreamCredential
from app.auth.providers.fakes import FakeSecretStore


class GitHubPATProvider(AuthProvider):
    def __init__(self, store: FakeSecretStore | None = None):
        self._store = store or FakeSecretStore()

    async def get_upstream_credentials(self, principal: Principal, upstream) -> UpstreamCredential:
        # REAL: replace with a call to the org's secret manager (e.g. AWS Secrets
        # Manager, HashiCorp Vault KV) scoped to principal.user_id.
        pat = self._store.get_pat(principal.user_id)
        return UpstreamCredential(headers={"Authorization": f"Bearer {pat}"})
