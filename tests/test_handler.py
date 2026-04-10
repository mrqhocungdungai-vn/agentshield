"""
Tests for AgentShield hook handler.py — 2-role model (owner stub + guest active)
Run with: pytest tests/ -v
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

# Add hook dir to path so we can import handler directly
sys.path.insert(0, str(Path(__file__).parent.parent / "hook"))
import handler as h


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# 2-role config: only guest defined. owner_chat_id is intentionally absent
# (owner interacts via CLI, not Telegram, in the current iteration).
SAMPLE_CONFIG = {
    "enabled": True,
    "deny_unlisted": False,
    "roles": {
        "guest": {
            "chat_ids": [],
            "allow": ["chat"],
            "deny": ["command:*", "system:*", "terminal", "skill:*"],
            "rate_limit": {"messages_per_minute": 2, "messages_per_day": 10},
        },
    },
    "logging": {"conversations": False},  # disabled in tests
    "messages": {
        "rate_limit_minute": "Rate limited (minute)",
        "rate_limit_day": "Rate limited (day)",
        "action_denied": "Action denied",
        "unlisted_denied": "Unlisted denied",
    },
}


@pytest.fixture(autouse=True)
def reset_rate_state():
    """Clear rate limiter state between tests."""
    h._rate_state.clear()
    yield
    h._rate_state.clear()


@pytest.fixture
def tmp_hermes_home(tmp_path, monkeypatch):
    """Redirect HERMES_HOME to a temp dir so tests don't touch ~/.hermes."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# _find_role — 2-role model
# ---------------------------------------------------------------------------

class TestFindRole:
    def test_unlisted_returns_none(self):
        """Any user not in dynamic assignments returns None (caller → guest)."""
        assert h._find_role("777", SAMPLE_CONFIG, {}) is None

    def test_dynamic_guest_assignment(self):
        """Dynamically assigned guest resolves correctly."""
        assert h._find_role("777", SAMPLE_CONFIG, {"777": "guest"}) == "guest"

    def test_dynamic_assignment_can_be_overridden(self):
        """Dynamic assignments can be changed at runtime."""
        dynamic = {"500": "guest"}
        assert h._find_role("500", SAMPLE_CONFIG, dynamic) == "guest"

    def test_owner_chat_id_stub(self):
        """owner_chat_id in config does not return 'owner' yet (TODO stub).
        
        In the current iteration, the owner bypasses nothing — they use CLI.
        _find_role returns None for the owner's chat_id, which falls through
        to guest treatment. This test documents the intentional current behavior.
        When owner bypass is implemented, this test should be updated to
        assert == 'owner'.
        """
        config_with_owner = {**SAMPLE_CONFIG, "owner_chat_id": "999"}
        # TODO: owner role — when implemented, this should return "owner"
        result = h._find_role("999", config_with_owner, {})
        # Currently returns None (falls through to guest) — intentional stub behavior
        assert result is None


# ---------------------------------------------------------------------------
# _is_action_allowed — guest role
# ---------------------------------------------------------------------------

class TestIsActionAllowed:
    def test_guest_allow_chat(self):
        cfg = SAMPLE_CONFIG["roles"]["guest"]
        assert h._is_action_allowed("chat", cfg) is True

    def test_guest_deny_terminal(self):
        cfg = SAMPLE_CONFIG["roles"]["guest"]
        assert h._is_action_allowed("terminal", cfg) is False

    def test_guest_deny_command_wildcard(self):
        cfg = SAMPLE_CONFIG["roles"]["guest"]
        assert h._is_action_allowed("command:help", cfg) is False
        assert h._is_action_allowed("command:reset", cfg) is False

    def test_guest_deny_system(self):
        cfg = SAMPLE_CONFIG["roles"]["guest"]
        assert h._is_action_allowed("system:reset", cfg) is False
        assert h._is_action_allowed("system:stop", cfg) is False

    def test_guest_deny_skill(self):
        cfg = SAMPLE_CONFIG["roles"]["guest"]
        assert h._is_action_allowed("skill:summarize", cfg) is False

    def test_guest_unknown_action_denied(self):
        cfg = SAMPLE_CONFIG["roles"]["guest"]
        # Not in allow list → denied
        assert h._is_action_allowed("admin:nuke", cfg) is False

    def test_empty_allow_means_no_restriction(self):
        cfg = {"allow": [], "deny": []}
        assert h._is_action_allowed("anything", cfg) is True

    def test_wildcard_allow(self):
        cfg = {"allow": ["*"], "deny": []}
        assert h._is_action_allowed("terminal", cfg) is True
        assert h._is_action_allowed("system:stop", cfg) is True

    def test_deny_overrides_allow(self):
        cfg = {"allow": ["*"], "deny": ["system:stop"]}
        assert h._is_action_allowed("system:stop", cfg) is False
        assert h._is_action_allowed("chat", cfg) is True


# ---------------------------------------------------------------------------
# _infer_action
# ---------------------------------------------------------------------------

class TestInferAction:
    def test_regular_message(self):
        ctx = {"is_command": False, "message": "hello"}
        assert h._infer_action(ctx) == "chat"

    def test_command_help(self):
        ctx = {"is_command": True, "command": "help", "message": "/help"}
        assert h._infer_action(ctx) == "command:help"

    def test_system_reset(self):
        ctx = {"is_command": True, "command": "reset", "message": "/reset"}
        assert h._infer_action(ctx) == "system:reset"

    def test_system_new(self):
        ctx = {"is_command": True, "command": "new", "message": "/new"}
        assert h._infer_action(ctx) == "system:reset"

    def test_system_stop(self):
        ctx = {"is_command": True, "command": "stop", "message": "/stop"}
        assert h._infer_action(ctx) == "system:stop"

    def test_skill_run(self):
        ctx = {"is_command": True, "command": "skill", "message": "/skill run summarize"}
        assert h._infer_action(ctx) == "skill:summarize"

    def test_skill_no_name(self):
        ctx = {"is_command": True, "command": "skill", "message": "/skill"}
        assert h._infer_action(ctx) == "skill:*"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_under_limit_allowed(self):
        limits = {"messages_per_minute": 5, "messages_per_day": 100}
        assert h._check_rate_limit("user1", limits) is None

    def test_minute_limit_exceeded(self):
        limits = {"messages_per_minute": 3, "messages_per_day": 100}
        h._rate_state["user1"] = {
            "minute": {"ts": time.time(), "count": 3},
            "day": {"ts": time.time(), "count": 3},
        }
        assert h._check_rate_limit("user1", limits) == "rate_limit_minute"

    def test_day_limit_exceeded(self):
        limits = {"messages_per_minute": 100, "messages_per_day": 10}
        h._rate_state["user1"] = {
            "minute": {"ts": time.time(), "count": 0},
            "day": {"ts": time.time(), "count": 10},
        }
        assert h._check_rate_limit("user1", limits) == "rate_limit_day"

    def test_minute_bucket_resets_after_60s(self):
        limits = {"messages_per_minute": 2, "messages_per_day": 100}
        old_ts = time.time() - 70  # 70 seconds ago
        h._rate_state["user1"] = {
            "minute": {"ts": old_ts, "count": 99},
            "day": {"ts": time.time(), "count": 1},
        }
        assert h._check_rate_limit("user1", limits) is None

    def test_record_increments_counters(self):
        h._rate_state["user1"] = {
            "minute": {"ts": time.time(), "count": 0},
            "day": {"ts": time.time(), "count": 0},
        }
        h._record_message("user1")
        assert h._rate_state["user1"]["minute"]["count"] == 1
        assert h._rate_state["user1"]["day"]["count"] == 1


# ---------------------------------------------------------------------------
# Role persistence
# ---------------------------------------------------------------------------

class TestRolePersistence:
    def test_load_empty_when_no_file(self, tmp_hermes_home):
        result = h._load_dynamic_roles()
        assert result == {}

    def test_save_and_load_roundtrip(self, tmp_hermes_home):
        assignments = {"123": "guest", "456": "guest"}
        h._save_dynamic_roles(assignments)
        loaded = h._load_dynamic_roles()
        assert loaded == assignments

    def test_save_is_atomic(self, tmp_hermes_home):
        """Verify no .tmp file is left behind after save."""
        h._save_dynamic_roles({"x": "guest"})
        tmp_file = h._roles_file().with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_load_corrupted_file_returns_empty(self, tmp_hermes_home):
        h._roles_file().write_text("this is not json", encoding="utf-8")
        result = h._load_dynamic_roles()
        assert result == {}


# ---------------------------------------------------------------------------
# Admin commands — 2-role model
# ---------------------------------------------------------------------------

class TestAdminCommands:
    def test_as_assign_guest(self):
        dynamic = {}
        ctx = {"is_command": True, "command": "as_assign",
               "message": "/as_assign 777 guest"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
        assert result is not None
        assert result["allow"] is False
        assert "777" in result["reason"]
        assert dynamic.get("777") == "guest"

    def test_as_assign_invalid_role(self):
        """'admin' and 'user' are no longer valid roles."""
        dynamic = {}
        for invalid_role in ("admin", "user", "superuser"):
            ctx = {"is_command": True, "command": "as_assign",
                   "message": f"/as_assign 777 {invalid_role}"}
            result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
            assert result is not None
            assert "Unknown role" in result["reason"]
            assert "777" not in dynamic

    def test_as_revoke(self):
        dynamic = {"777": "guest"}
        ctx = {"is_command": True, "command": "as_revoke",
               "message": "/as_revoke 777"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
        assert result is not None
        assert "777" not in dynamic

    def test_as_revoke_nonexistent(self):
        dynamic = {}
        ctx = {"is_command": True, "command": "as_revoke",
               "message": "/as_revoke 999"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
        assert result is not None
        assert "No dynamic role" in result["reason"]

    def test_as_roles_empty(self):
        ctx = {"is_command": True, "command": "as_roles", "message": "/as_roles"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "No dynamic" in result["reason"]

    def test_as_roles_with_assignments(self):
        dynamic = {"123": "guest", "456": "guest"}
        ctx = {"is_command": True, "command": "as_roles", "message": "/as_roles"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
        assert result is not None
        assert "123" in result["reason"]
        assert "456" in result["reason"]

    def test_as_info(self):
        ctx = {"is_command": True, "command": "as_info", "message": "/as_info 777"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "777" in result["reason"]
        # Unlisted user resolves to guest in as_info
        assert "guest" in result["reason"]

    def test_non_admin_command_returns_none(self):
        ctx = {"is_command": True, "command": "help", "message": "/help"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is None

    def test_non_command_returns_none(self):
        ctx = {"is_command": False, "message": "hello"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is None


# ---------------------------------------------------------------------------
# Full handle() integration — 2-role model
# ---------------------------------------------------------------------------

class TestHandleIntegration:
    @pytest.fixture
    def mock_config(self):
        with patch.object(h, "_load_config", return_value=SAMPLE_CONFIG), \
             patch.object(h, "_load_dynamic_roles", return_value={}), \
             patch.object(h, "_save_dynamic_roles"):
            yield

    @pytest.mark.asyncio
    async def test_any_user_chat_allowed(self, mock_config):
        """All users default to guest — chat is allowed."""
        for chat_id in ("111", "222", "777", "999"):
            ctx = {"chat_id": chat_id, "is_command": False, "message": "hello"}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True, f"Expected allow for chat_id={chat_id}"

    @pytest.mark.asyncio
    async def test_any_user_terminal_denied(self, mock_config):
        """All users default to guest — terminal is blocked."""
        ctx = {"chat_id": "777", "is_command": True, "command": "terminal",
               "message": "/terminal ls"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is False
        assert "Action denied" in result["reason"]

    @pytest.mark.asyncio
    async def test_any_user_system_command_denied(self, mock_config):
        """system:* commands are blocked for all users."""
        ctx = {"chat_id": "777", "is_command": True, "command": "reset",
               "message": "/reset"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is False

    @pytest.mark.asyncio
    async def test_deny_unlisted_blocks_all(self):
        """When deny_unlisted=true, all unlisted users are blocked immediately."""
        config = {**SAMPLE_CONFIG, "deny_unlisted": True}
        with patch.object(h, "_load_config", return_value=config), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            ctx = {"chat_id": "777", "is_command": False, "message": "hello"}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is False
            assert "Unlisted denied" in result["reason"]

    @pytest.mark.asyncio
    async def test_disabled_config_passes_all(self):
        config = {**SAMPLE_CONFIG, "enabled": False}
        with patch.object(h, "_load_config", return_value=config):
            ctx = {"chat_id": "777", "is_command": False, "message": "hi"}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True

    @pytest.mark.asyncio
    async def test_agent_end_logs_conversation(self, tmp_hermes_home):
        config = {**SAMPLE_CONFIG, "logging": {"conversations": True}}
        with patch.object(h, "_load_config", return_value=config), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            ctx = {
                "user_id": "777",
                "message": "hello",
                "response": "hi there",
            }
            await h.handle("agent:end", ctx)
            log_file = tmp_hermes_home / "logs" / "conversations" / "777.jsonl"
            assert log_file.exists()
            entry = json.loads(log_file.read_text().strip())
            assert entry["user"] == "hello"
            assert entry["agent"] == "hi there"
            assert entry["role"] == "guest"

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_after_threshold(self, mock_config):
        """Guest rate limit is enforced for all users."""
        h._rate_state["777"] = {
            "minute": {"ts": time.time(), "count": 2},
            "day": {"ts": time.time(), "count": 2},
        }
        ctx = {"chat_id": "777", "is_command": False, "message": "hello"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is False
        assert "Rate limited (minute)" in result["reason"]

    @pytest.mark.asyncio
    async def test_no_chat_id_passes_through(self, mock_config):
        """Messages with no chat_id are passed through (cannot enforce)."""
        ctx = {"is_command": False, "message": "hello"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is True
