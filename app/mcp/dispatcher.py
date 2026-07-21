"""
MCP Dispatcher — the core routing brain of nom-py.

Handles JSON-RPC methods:
- initialize
- tools/list
- tools/call

Enforces auth and policy before forwarding to the upstream, and resolves a
per-upstream outbound credential (see app/auth/providers) before every
tools/call — read-only tools included.
"""
import logging
from typing import Any

from app.auth.models import Principal
from app.auth.providers.base import ConfigError
from app.auth.providers.registry import ProviderRegistry, default_registry
from app.config import settings
from app.mcp.server_registry import ServerRegistry, load_server_registry
from app.mcp.upstream import UpstreamClient
from app.policy.engine import PolicyEngine
from app.policy.errors import PolicyDenied
from app.safety.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)


class MCPDispatcher:
    def __init__(
        self,
        upstream: UpstreamClient,
        policy: PolicyEngine,
        idempotency: IdempotencyStore | None = None,
        servers: ServerRegistry | None = None,
        providers: ProviderRegistry | None = None,
    ):
        self.upstream = upstream
        self.policy = policy
        self.idempotency = idempotency or IdempotencyStore()
        self.servers = servers or load_server_registry()
        self.providers = providers or default_registry()

    async def handle(
        self, msg: dict[str, Any], principal: Principal, ctx=None
    ) -> dict[str, Any] | None:
        method = msg.get("method")
        msg_id = msg.get("id")
        is_notification = msg_id is None

        logger.info(
            "MCP request: method=%s id=%s user=%s",
            method, msg_id, principal.user_id,
        )

        if method == "initialize":
            result = await self._handle_initialize(msg, ctx)
        elif method == "tools/list":
            result = await self._handle_tools_list(msg, principal, ctx)
        elif method == "tools/call":
            result = await self._handle_tools_call(msg, principal, ctx)
        elif is_notification:
            # Notifications are fire-and-forget lifecycle signals — log and drop
            logger.info("Notification received: %s (ignored)", method)
            if ctx is not None:
                ctx.record("notification.received", method=method)
            result = None
        else:
            result = self._error(msg_id, -32601, f"Method not supported: {method}")

        if ctx is not None:
            if is_notification:
                outcome = "notification"
            elif result and "error" in result:
                outcome = "error"
            else:
                outcome = "ok"
            ctx.record("dispatch.complete", outcome=outcome)
        return result

    async def _handle_initialize(self, msg: dict[str, Any], ctx=None) -> dict[str, Any]:
        upstream_result = await self.upstream.forward(settings.upstream_endpoint, msg, ctx=ctx)
        if "result" in upstream_result:
            upstream_result["result"]["serverInfo"] = {
                "name": "nom-py",
                "version": "0.4.0",
            }
            # Guarantee capabilities.tools is present even if upstream omits it
            if "capabilities" not in upstream_result["result"]:
                upstream_result["result"]["capabilities"] = {"tools": {}}
        return upstream_result

    async def _handle_tools_list(
        self, msg: dict[str, Any], principal: Principal, ctx=None
    ) -> dict[str, Any]:
        upstream_result = await self.upstream.forward(settings.upstream_endpoint, msg, ctx=ctx)
        if "result" in upstream_result and "tools" in upstream_result["result"]:
            all_tools = upstream_result["result"]["tools"]
            filtered = self.policy.filter_tools_list(principal, all_tools)
            upstream_result["result"]["tools"] = filtered
        return upstream_result

    async def _handle_tools_call(
        self, msg: dict[str, Any], principal: Principal, ctx=None
    ) -> dict[str, Any]:
        params = msg.get("params", {}) or {}
        exposed_name = params.get("name", "")
        args = params.get("arguments", {}) or {}

        # 1. Resolve routing first — an unknown/unnamespaced tool is a client error,
        #    not a policy or credential decision.
        try:
            route, original_name = self.servers.resolve(exposed_name)
        except ConfigError as e:
            return self._error(msg.get("id"), -32602, str(e))

        # 2. Policy decides before any credential is touched — a denied call must
        #    never cause a provider (secret store, vault, token minter) to be invoked.
        #    Rules are keyed by the tool's original (un-namespaced) name — the same
        #    tool is governed by the same rule no matter which upstream exposes it.
        try:
            self.policy.evaluate_tool_call(principal, original_name, ctx)
        except PolicyDenied as e:
            return self._error(msg.get("id"), e.code, str(e))

        # 3. Only an allowed call gets a provider looked up...
        try:
            provider = self.providers.for_upstream(route)
        except ConfigError as e:
            return self._error(msg.get("id"), -32000, str(e))

        # 4. ...and only a resolved credential may proceed. Any failure here means
        #    we FAIL CLOSED: never forward to the upstream unauthenticated.
        try:
            cred = await provider.get_upstream_credentials(principal, route)
        except Exception as e:
            logger.error("Credential resolution failed: upstream=%s error=%s", route.name, e)
            if ctx is not None:
                ctx.record("credential.failed", upstream=route.name, error=str(e))
            return self._error(msg.get("id"), -32000, f"Credential resolution failed for '{route.name}'")

        if ctx is not None:
            # Record the lease_id (an audit reference) — never cred.headers or the secret.
            ctx.record(
                "credential.resolved",
                provider=type(provider).__name__,
                upstream=route.name,
                lease_id=cred.lease_id,
            )

        rule = self.policy.rules.get(original_name, {})
        forward_msg = {**msg, "params": {**params, "name": original_name}}

        try:
            if not rule.get("mutating"):
                # Read-only tool — forward directly, no idempotency overhead
                return await self.upstream.forward(route.url, forward_msg, headers=cred.headers, ctx=ctx)

            # Mutating tool — serialise concurrent identical calls under a per-key lock
            idempotency_key = self.idempotency.key_for(
                principal.user_id,
                exposed_name,  # per-upstream identity: same tool name on two upstreams != same op
                args,
                params.get("idempotency_key"),
            )
            async with self.idempotency.lock_for(idempotency_key):
                cached = self.idempotency.get(idempotency_key)
                if cached:
                    if ctx is not None:
                        ctx.record("idempotency.hit", key=idempotency_key)
                    return cached
                if ctx is not None:
                    ctx.record("idempotency.miss", key=idempotency_key)

                result = await self.upstream.forward(route.url, forward_msg, headers=cred.headers, ctx=ctx)

                # Only cache confirmed successes — never persist upstream errors
                if "error" not in result:
                    self.idempotency.put(idempotency_key, result)

            return result
        finally:
            await provider.release(cred)

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }
