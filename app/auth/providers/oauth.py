"""
GoogleOAuthProvider — mints short-lived OAuth access tokens per user and
caches them until expiry, only refreshing once the cached token has lapsed.
"""
import time

from app.auth.models import Principal
from app.auth.providers.base import AuthProvider, UpstreamCredential
from app.auth.providers.fakes import FakeOAuthTokenEndpoint


class GoogleOAuthProvider(AuthProvider):
    def __init__(self, token_endpoint: FakeOAuthTokenEndpoint | None = None):
        self._endpoint = token_endpoint or FakeOAuthTokenEndpoint()
        self._cache: dict[str, tuple[str, float]] = {}

    async def get_upstream_credentials(self, principal: Principal, upstream) -> UpstreamCredential:
        cached = self._cache.get(principal.user_id)
        now = time.time()
        if cached is not None and cached[1] > now:
            access_token, expires_at = cached
        else:
            # REAL: replace with POST https://oauth2.googleapis.com/token
            # (refresh_token grant) using the user's stored refresh token.
            minted = self._endpoint.mint_access_token(principal.user_id)
            access_token = minted["access_token"]
            expires_at = now + minted["expires_in"]
            self._cache[principal.user_id] = (access_token, expires_at)

        return UpstreamCredential(
            headers={"Authorization": f"Bearer {access_token}"},
            expires_at=expires_at,
        )
