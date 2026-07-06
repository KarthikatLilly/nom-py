"""
Auth-related data models.
"""
from dataclasses import dataclass, field


@dataclass
class Principal:
    """Represents an authenticated user with their group memberships."""
    user_id: str
    groups: list[str] = field(default_factory=list)
    token: str = ""

    def in_group(self, group: str) -> bool:
        return group in self.groups

    def in_any_group(self, groups: list[str]) -> bool:
        return any(g in self.groups for g in groups)