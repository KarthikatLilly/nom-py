"""
Idempotency — prevents duplicate mutating tool calls.
"""
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

    def key_for(self, user_id: str, tool: str, args: dict, explicit_key: str | None) -> str:
        if explicit_key:
            return f"{user_id}:{tool}:{explicit_key}"
        payload = json.dumps({"u": user_id, "t": tool, "a": args}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

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