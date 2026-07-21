"""
EnterpriseCAProvider — checks out a short-lived credential lease from the
enterprise vault (CyberArk-style) per call, and releases (invalidates) the
lease once the call finishes so it can't be replayed.
"""
from app.auth.models import Principal
from app.auth.providers.base import AuthProvider, UpstreamCredential
from app.auth.providers.fakes import FakeVaultClient


class EnterpriseCAProvider(AuthProvider):
    def __init__(self, vault: FakeVaultClient | None = None):
        self._vault = vault or FakeVaultClient()

    async def get_upstream_credentials(self, principal: Principal, upstream) -> UpstreamCredential:
        safe = upstream.vault_safe
        if not safe:
            raise ValueError(
                f"Server '{upstream.name}' has no vault_safe configured for ca auth_mode"
            )

        # REAL: replace with a CyberArk Central Credential Provider / Conjur lease call.
        lease = self._vault.lease(safe=safe, requested_by=principal.user_id)
        return UpstreamCredential(
            headers={"Authorization": f"Bearer {lease.secret}"},
            expires_at=lease.expires_at,
            lease_id=lease.id,
        )

    async def release(self, cred: UpstreamCredential) -> None:
        if cred.lease_id:
            # REAL: replace with the vault's lease-revoke call.
            self._vault.invalidate(cred.lease_id)
