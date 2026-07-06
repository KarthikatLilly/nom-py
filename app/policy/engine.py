"""
Policy engine — evaluates tool access against policy.yaml.
"""
import logging

from app.auth.models import Principal
from app.config import settings
from app.policy.errors import PolicyDenied

logger = logging.getLogger(__name__)


class PolicyEngine:
    def __init__(self):
        self.rules = settings.tool_rules

    def evaluate_tool_call(self, principal: Principal, tool_name: str) -> None:
        """
        Check if the principal can call the given tool.
        Raises PolicyDenied if not allowed.
        """
        rule = self.rules.get(tool_name)

        # If tool has no policy rule, default DENY (least privilege)
        if rule is None:
            logger.warning("No policy rule for tool: %s — denying", tool_name)
            raise PolicyDenied(
                f"Tool '{tool_name}' has no policy rule defined"
            )

        # Global deny
        if not rule.get("allow", False):
            reason = rule.get("reason", "not permitted")
            logger.info(
                "Policy denied: user=%s tool=%s reason=%s",
                principal.user_id, tool_name, reason,
            )
            raise PolicyDenied(f"Tool '{tool_name}' denied: {reason}")

        # Group check
        allowed_groups = rule.get("allowed_groups", [])
        if allowed_groups and not principal.in_any_group(allowed_groups):
            logger.info(
                "Policy denied: user=%s tool=%s not in allowed_groups=%s",
                principal.user_id, tool_name, allowed_groups,
            )
            raise PolicyDenied(
                f"Tool '{tool_name}' requires one of groups: {allowed_groups}"
            )

        logger.info(
            "Policy allow: user=%s tool=%s", principal.user_id, tool_name,
        )

    def filter_tools_list(
        self, principal: Principal, tools: list[dict]
    ) -> list[dict]:
        """
        Filter the tools/list response to only include tools this user can call.
        """
        allowed = []
        for tool in tools:
            name = tool.get("name")
            try:
                self.evaluate_tool_call(principal, name)
                allowed.append(tool)
            except PolicyDenied:
                pass
        return allowed