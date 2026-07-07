"""
Idempotency -- prevents duplicate mutating tool calls.
"""
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class IdempotencyEntry:
    result: dict[str, Any]
    timestamp: float


class IdempotencyStore:
    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict[str, IdempotencyEntry] = {}
        self.ttl = ttl_seconds
        self._key_locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, key: str) -> asyncio.Lock:
        """Get-or-create a per-key asyncio lock.

        Safe without a meta-lock because asyncio is single-threaded:
        no two coroutines can interleave at this point.
        """
        if key not in self._key_locks:
            self._key_locks[key] = asyncio.Lock()
        return self._key_locks[key]

    def key_for(self, user_id: str, tool: str, args: dict, explicit_key: str | None) -> str:
        """Produce a canonical idempotency key.

        Uses sort_keys=True and compact separators so that arg dicts
        with the same entries in different insertion order hash identically.
        """
        if explicit_key:
            return f"{user_id}:{tool}:{explicit_key}"
        canonical_args = json.dumps(args, sort_keys=True, separators=(',', ':'))
        key_input = f"{user_id}:{tool}:{canonical_args}"
        return hashlib.sha256(key_input.encode()).hexdigest()[:32]

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if time.time() - entry.timestamp > self.ttl:
            self._store.pop(key, None)
            return None
        return entry.result

    def put(self, key: str, result: dict[str, Any]) -> None:
        self._store[key] = IdempotencyEntry(result=result, timestamp=time.time())
