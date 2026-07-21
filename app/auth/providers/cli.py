"""
GCPCLIProvider — mints a short-lived, impersonated service-account token for
each call. Deliberately never touches a local gcloud/ADC session: NOM is a
shared service and must not inherit whatever identity happens to be logged
into the host's CLI.
"""
import time

from app.auth.models import Principal
from app.auth.providers.base import AuthProvider, UpstreamCredential
from app.auth.providers.fakes import FakeTokenMinter


class GCPCLIProvider(AuthProvider):
    def __init__(self, minter: FakeTokenMinter | None = None):
        self._minter = minter or FakeTokenMinter()

    async def get_upstream_credentials(self, principal: Principal, upstream) -> UpstreamCredential:
        service_account = upstream.service_account
        if not service_account:
            raise ValueError(
                f"Server '{upstream.name}' has no service_account configured for cli auth_mode"
            )

        # REAL: replace with IAM Credentials API generateAccessToken, impersonating
        # `service_account` (never a local `gcloud auth` session).
        minted = self._minter.impersonate(service_account)
        return UpstreamCredential(
            headers={"Authorization": f"Bearer {minted['token']}"},
            expires_at=time.time() + minted["expires_in"],
        )
