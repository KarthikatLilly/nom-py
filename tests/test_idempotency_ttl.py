"""
TTL expiry test for IdempotencyStore.

Proves that entries are evicted after ttl_seconds and not returned as hits.
"""
import time

from app.safety.idempotency import IdempotencyStore


def test_ttl_expiry():
    store = IdempotencyStore(ttl_seconds=1)

    store.put("k", {"result": "x"})
    assert store.get("k") == {"result": "x"}  # present before TTL

    time.sleep(1.1)

    assert store.get("k") is None  # evicted after TTL
