"""
Tests for 2-role model behavior in AgentShield.

These tests document the intended behavior of the guest-only active model:
- guest is the only enforced role
- owner is planned / stubbed (# TODO)
- admin and user roles no longer exist
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "hook"))
import handler as h


# Minimal 2-role config for these tests
CONFIG_2ROLE = {
    "enabled": True,
    "deny_unlisted": False,
    "roles": {
        "guest": {
            "allow": ["chat"],
            "deny": ["command:*", "system:*", "terminal", "skill:*"],
            "rate_limit": {"messages_per_minute": 5, "messages_per_day": 50},
        },
    },
    "logging": {"conversations": False},
    "messages": {
        "action_denied": "Action denied",
        "unlisted_denied": "Unlisted denied",
    },
}


@pytest.fixture(autouse=True)
def reset_rate_state():
    h._rate_state.clear()
    yield
    h._rate_state.clear()


# ---------------------------------------------------------------------------
# 2-role model: everyone is guest
# ---------------------------------------------------------------------------

class TestTwoRoleModel:
    def test_all_unknown_users_resolve_to_none(self):
        """_find_role returns None for all users not in dynamic assignments.
        The caller (handle) then assigns guest role to them.
        """
        for chat_id in ("100", "200", "300", "999"):
            assert h._find_role(chat_id, CONFIG_2ROLE, {}) is None

    def test_dynamic_guest_resolves(self):
        """Dynamically assigned guest resolves correctly."""
        assert h._find_role("500", CONFIG_2ROLE, {"500": "guest"}) == "guest"

    def test_admin_role_does_not_exist(self):
        """admin is not a valid role in 2-role model.
        /as_assign should reject it as an unknown role.
        """
        dynamic = {}
        ctx = {"is_command": True, "command": "as_assign",
               "message": "/as_assign 100 admin"}
        result = h._handle_admin_command(ctx, CONFIG_2ROLE, dynamic)
        assert result is not None
        assert "Unknown role" in result["reason"]
        assert "100" not in dynamic

    def test_user_role_does_not_exist(self):
        """user is not a valid role in 2-role model."""
        dynamic = {}
        ctx = {"is_command": True, "command": "as_assign",
               "message": "/as_assign 100 user"}
        result = h._handle_admin_command(ctx, CONFIG_2ROLE, dynamic)
        assert result is not None
        assert "Unknown role" in result["reason"]
        assert "100" not in dynamic

    def test_guest_is_only_assignable_role(self):
        """Only 'guest' is a valid role for /as_assign."""
        dynamic = {}
        ctx = {"is_command": True, "command": "as_assign",
               "message": "/as_assign 100 guest"}
        result = h._handle_admin_command(ctx, CONFIG_2ROLE, dynamic)
        assert result is not None
        assert "100" in result["reason"]
        assert dynamic.get("100") == "guest"


# ---------------------------------------------------------------------------
# guest role behavior
# ---------------------------------------------------------------------------

class TestGuestRoleBehavior:
    def test_guest_can_chat(self):
        cfg = CONFIG_2ROLE["roles"]["guest"]
        assert h._is_action_allowed("chat", cfg) is True

    def test_guest_cannot_use_commands(self):
        cfg = CONFIG_2ROLE["roles"]["guest"]
        for cmd in ("command:help", "command:model", "command:reset"):
            assert h._is_action_allowed(cmd, cfg) is False

    def test_guest_cannot_use_system_actions(self):
        cfg = CONFIG_2ROLE["roles"]["guest"]
        for action in ("system:reset", "system:stop"):
            assert h._is_action_allowed(action, cfg) is False

    def test_guest_cannot_use_skills(self):
        cfg = CONFIG_2ROLE["roles"]["guest"]
        for skill in ("skill:summarize", "skill:translate", "skill:*"):
            assert h._is_action_allowed(skill, cfg) is False

    def test_guest_cannot_use_terminal(self):
        cfg = CONFIG_2ROLE["roles"]["guest"]
        assert h._is_action_allowed("terminal", cfg) is False


# ---------------------------------------------------------------------------
# owner stub — documents planned behavior
# ---------------------------------------------------------------------------

class TestOwnerStub:
    def test_owner_chat_id_currently_resolves_to_none(self):
        """Documents the intentional stub: owner_chat_id is set in config but
        _find_role returns None (not 'owner') because owner bypass is not yet
        implemented. When owner is implemented, this test should be updated.
        """
        config_with_owner = {**CONFIG_2ROLE, "owner_chat_id": "999"}
        result = h._find_role("999", config_with_owner, {})
        # TODO: owner role — when implemented, assert result == "owner"
        assert result is None  # intentional stub behavior

    @pytest.mark.asyncio
    async def test_owner_currently_treated_as_guest(self):
        """Owner's messages currently go through guest checks (stub behavior).
        When owner bypass is implemented, owner should skip all checks.
        """
        config_with_owner = {**CONFIG_2ROLE, "owner_chat_id": "999"}
        with patch.object(h, "_load_config", return_value=config_with_owner), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            # Chat: allowed (guest allows chat)
            ctx = {"chat_id": "999", "is_command": False, "message": "hello"}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True

            # Terminal: blocked (guest blocks terminal — owner bypass not implemented)
            ctx = {"chat_id": "999", "is_command": True, "command": "terminal",
                   "message": "/terminal ls"}
            result = await h.handle("before_message", ctx)
            # TODO: owner role — when implemented, this should be allow=True
            assert result["allow"] is False  # stub: owner gets guest treatment
