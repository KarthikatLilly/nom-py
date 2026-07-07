"""
Loads nom-py configuration from policy.yaml.
"""
from pathlib import Path
from typing import Any

import yaml


class Settings:
    def __init__(self, policy_path: str = "config/policy.yaml"):
        self.policy_path = Path(policy_path)
        self._policy: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        with open(self.policy_path, "r") as f:
            self._policy = yaml.safe_load(f) or {}

    @property
    def upstream_endpoint(self) -> str:
        return self._policy.get("upstream", {}).get("endpoint", "")

    @property
    def auth_enabled(self) -> bool:
        return self._policy.get("auth", {}).get("enabled", False)

    @property
    def admin_token(self) -> str:
        return self._policy.get("auth", {}).get("admin_token", "")

    @property
    def tokens(self) -> dict[str, dict[str, Any]]:
        return self._policy.get("auth", {}).get("tokens", {})

    @property
    def tool_rules(self) -> dict[str, dict[str, Any]]:
        return self._policy.get("tools", {})

    @property
    def raw(self) -> dict[str, Any]:
        return self._policy


settings = Settings()