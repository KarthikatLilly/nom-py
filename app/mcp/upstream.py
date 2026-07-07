"""
UpstreamClient — forwards MCP JSON-RPC messages to the configured upstream.
"""
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class UpstreamClient:
    def __init__(self, endpoint: str, timeout: float = 15.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def forward(self, msg: dict[str, Any], ctx=None) -> dict[str, Any]:
        logger.debug("Forwarding to upstream: %s", self.endpoint)
        try:
            t0 = time.monotonic()
            response = await self._client.post(self.endpoint, json=msg)
            if ctx is not None:
                ctx.record(
                    "upstream.call",
                    latency_ms=round((time.monotonic() - t0) * 1000, 2),
                    status=response.status_code,
                )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("Upstream error: %s", e)
            return {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {
                    "code": -32000,
                    "message": f"Upstream error: {e}",
                },
            }

    async def close(self) -> None:
        await self._client.aclose()
