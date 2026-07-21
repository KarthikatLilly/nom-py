"""
ServerConfig — routing + credential metadata for one upstream MCP server, and
ServerRegistry — resolves an exposed (namespaced) tool name back to its
server and original tool name.

Tools are exposed to callers as "<namespace>__<tool_name>" so a single flat
tools/list can mix tools from multiple upstreams without collisions.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.auth.providers.base import ConfigError


@dataclass
class ServerConfig:
    name: str
    url: str
    namespace: str
    auth_mode: str
    vault_safe: str | None = None
    service_account: str | None = None


class ServerRegistry:
    def __init__(self, servers: dict[str, ServerConfig]):
        self._servers = servers
        self._by_namespace = {s.namespace: s for s in servers.values()}

    def resolve(self, exposed_tool: str) -> tuple[ServerConfig, str]:
        """Split '<namespace>__<tool>' into (ServerConfig, original_tool_name)."""
        if "__" not in exposed_tool:
            raise ConfigError(f"Tool '{exposed_tool}' is not namespaced (expected '<namespace>__<tool>')")
        namespace, _, original_name = exposed_tool.partition("__")
        server = self._by_namespace.get(namespace)
        if server is None:
            raise ConfigError(f"Unknown upstream namespace '{namespace}' for tool '{exposed_tool}'")
        return server, original_name


def load_server_registry(path: str = "config/servers.yaml") -> ServerRegistry:
    with open(Path(path), "r") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    servers: dict[str, ServerConfig] = {}
    for name, cfg in raw.get("servers", {}).items():
        servers[name] = ServerConfig(
            name=name,
            url=cfg["url"],
            namespace=cfg.get("namespace", name),
            auth_mode=cfg["auth_mode"],
            vault_safe=cfg.get("vault_safe"),
            service_account=cfg.get("service_account"),
        )
    return ServerRegistry(servers)
