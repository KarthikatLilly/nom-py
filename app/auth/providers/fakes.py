"""
Fake stand-ins for the real external systems each provider talks to
(GitHub secret store, Google OAuth token endpoint, GCP IAM token minter,
enterprise vault). Each mirrors the shape of its real counterpart closely
enough that swapping in the real SDK is a drop-in replacement at the
`# REAL:` markers in the provider modules.
"""
import time
import uuid
from dataclasses import dataclass


class FakeSecretStore:
    """Stand-in for a secret manager holding per-user GitHub PATs."""

    def __init__(self, secrets: dict[str, str] | None = None):
        self._secrets = secrets or {
            "alice": "ghp_fake_alice_0000000000000000",
            "bob": "ghp_fake_bob_00000000000000000000",
        }

    def get_pat(self, user_id: str) -> str:
        try:
            return self._secrets[user_id]
        except KeyError:
            raise KeyError(f"No GitHub PAT provisioned for user '{user_id}'")


class FakeOAuthTokenEndpoint:
    """Stand-in for Google's OAuth token endpoint (refresh_token grant)."""

    def __init__(self):
        self.calls = 0

    def mint_access_token(self, user_id: str, ttl_seconds: float = 300.0) -> dict:
        self.calls += 1
        return {
            "access_token": f"fake-google-token-{user_id}-{uuid.uuid4().hex[:8]}",
            "expires_in": ttl_seconds,
        }


class FakeTokenMinter:
    """Stand-in for the GCP IAM Credentials API's generateAccessToken (impersonation)."""

    def __init__(self):
        self.calls = 0

    def impersonate(self, service_account: str, ttl_seconds: float = 600.0) -> dict:
        self.calls += 1
        return {
            "token": f"fake-impersonated-{service_account}-{uuid.uuid4().hex[:8]}",
            "expires_in": ttl_seconds,
        }


@dataclass
class FakeLease:
    id: str
    secret: str
    expires_at: float
    invalidated: bool = False


class FakeVaultClient:
    """Stand-in for an enterprise vault (e.g. CyberArk) issuing short-lived leases."""

    def __init__(self):
        self._leases: dict[str, FakeLease] = {}

    def lease(self, safe: str, requested_by: str, ttl_seconds: float = 300.0) -> FakeLease:
        lease = FakeLease(
            id=f"lease-{safe}-{uuid.uuid4().hex[:8]}",
            secret=f"fake-ca-secret-{safe}-{uuid.uuid4().hex[:8]}",
            expires_at=time.time() + ttl_seconds,
        )
        self._leases[lease.id] = lease
        return lease

    def invalidate(self, lease_id: str) -> None:
        lease = self._leases.get(lease_id)
        if lease is not None:
            lease.invalidated = True

    def is_invalidated(self, lease_id: str) -> bool:
        lease = self._leases.get(lease_id)
        return bool(lease and lease.invalidated)
