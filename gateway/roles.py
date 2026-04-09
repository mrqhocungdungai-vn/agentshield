"""
Role-based access control engine for AgentShield.

Determines what actions a user is allowed to perform
based on their assigned role and the config rules.
"""

from __future__ import annotations
import fnmatch
from typing import Dict, Optional
from gateway.config import Config, RoleConfig


class RoleEngine:
    def __init__(self, config: Config):
        self.config = config
        self._user_roles: Dict[str, str] = {}  # chat_id -> role_name

        # Pre-index chat_ids from role definitions
        for role_name, role_cfg in config.roles.items():
            for chat_id in role_cfg.chat_ids:
                self._user_roles[str(chat_id)] = role_name

    def get_role(self, chat_id: str) -> str:
        """Return the role name for a given chat_id."""
        if str(chat_id) == str(self.config.telegram.owner_chat_id):
            return "owner"
        return self._user_roles.get(str(chat_id), self.config.default_role)

    def assign_role(self, chat_id: str, role_name: str) -> None:
        """Dynamically assign a role to a user (e.g., after payment)."""
        self._user_roles[str(chat_id)] = role_name

    def is_allowed(self, chat_id: str, action: str) -> bool:
        """
        Check if a chat_id is allowed to perform an action.
        Owner always allowed. Others checked against allow/deny lists.
        """
        role_name = self.get_role(chat_id)

        # Owner has no restrictions
        if role_name == "owner":
            return True

        role_cfg: Optional[RoleConfig] = self.config.roles.get(role_name)
        if role_cfg is None:
            return False

        # Check deny list first (deny overrides allow)
        for pattern in role_cfg.deny:
            if fnmatch.fnmatch(action, pattern):
                return False

        # Check allow list
        for pattern in role_cfg.allow:
            if pattern == "*" or fnmatch.fnmatch(action, pattern):
                return True

        return False

    def get_rate_limit(self, chat_id: str):
        """Return rate limit config for user, or None if unlimited."""
        role_name = self.get_role(chat_id)
        if role_name == "owner":
            return None
        role_cfg = self.config.roles.get(role_name)
        if role_cfg:
            return role_cfg.rate_limit
        return None
