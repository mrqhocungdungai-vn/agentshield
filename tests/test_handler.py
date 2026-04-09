"""
Tests for AgentShield hook handler.py
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

SAMPLE_CONFIG = {
    "enabled": True,
    "owner_chat_id": "999",
    "deny_unlisted": False,
    "roles": {
        "admin": {
            "chat_ids": ["111"],
            "allow": ["*"],
            "rate_limit": {"messages_per_minute": 60, "messages_per_day": 2000},
        },
        "user": {
            "chat_ids": ["222"],
            "allow": ["chat", "skill:*", "command:help", "command:reset"],
            "deny": ["terminal", "system:stop"],
            "rate_limit": {"messages_per_minute": 5, "messages_per_day": 100},
        },
        "guest": {
            "chat_ids": [],
            "allow": ["chat"],
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
# _find_role
# ---------------------------------------------------------------------------

class TestFindRole:
    def test_owner_by_config(self):
        assert h._find_role("999", SAMPLE_CONFIG, {}) == "owner"

    def test_static_admin(self):
        assert h._find_role("111", SAMPLE_CONFIG, {}) == "admin"

    def test_static_user(self):
        assert h._find_role("222", SAMPLE_CONFIG, {}) == "user"

    def test_unlisted(self):
        assert h._find_role("777", SAMPLE_CONFIG, {}) is None

    def test_dynamic_overrides_static(self):
        # "222" is static user, but dynamically promoted to admin
        assert h._find_role("222", SAMPLE_CONFIG, {"222": "admin"}) == "admin"

    def test_dynamic_assignment(self):
        # "777" is unlisted, but dynamically assigned guest
        assert h._find_role("777", SAMPLE_CONFIG, {"777": "guest"}) == "guest"


# ---------------------------------------------------------------------------
# _is_action_allowed
# ---------------------------------------------------------------------------

class TestIsActionAllowed:
    def test_admin_wildcard(self):
        cfg = {"allow": ["*"]}
        assert h._is_action_allowed("terminal", cfg) is True
        assert h._is_action_allowed("system:stop", cfg) is True

    def test_user_allow_chat(self):
        cfg = SAMPLE_CONFIG["roles"]["user"]
        assert h._is_action_allowed("chat", cfg) is True

    def test_user_allow_skill_wildcard(self):
        cfg = SAMPLE_CONFIG["roles"]["user"]
        assert h._is_action_allowed("skill:summarize", cfg) is True
        assert h._is_action_allowed("skill:translate", cfg) is True

    def test_user_deny_terminal(self):
        cfg = SAMPLE_CONFIG["roles"]["user"]
        assert h._is_action_allowed("terminal", cfg) is False

    def test_user_deny_system_stop(self):
        cfg = SAMPLE_CONFIG["roles"]["user"]
        assert h._is_action_allowed("system:stop", cfg) is False

    def test_user_unknown_action_denied(self):
        cfg = SAMPLE_CONFIG["roles"]["user"]
        # "admin:nuke" not in allow list
        assert h._is_action_allowed("admin:nuke", cfg) is False

    def test_empty_allow_means_no_restriction(self):
        cfg = {"allow": [], "deny": []}
        assert h._is_action_allowed("anything", cfg) is True


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
        assignments = {"123": "admin", "456": "user"}
        h._save_dynamic_roles(assignments)
        loaded = h._load_dynamic_roles()
        assert loaded == assignments

    def test_save_is_atomic(self, tmp_hermes_home):
        """Verify no .tmp file is left behind after save."""
        h._save_dynamic_roles({"x": "y"})
        tmp_file = h._roles_file().with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_load_corrupted_file_returns_empty(self, tmp_hermes_home):
        h._roles_file().write_text("this is not json", encoding="utf-8")
        result = h._load_dynamic_roles()
        assert result == {}


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

class TestAdminCommands:
    def test_as_assign(self):
        dynamic = {}
        ctx = {"is_command": True, "command": "as_assign",
               "message": "/as_assign 777 user"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
        assert result is not None
        assert result["allow"] is False
        assert "777" in result["reason"]
        assert dynamic.get("777") == "user"

    def test_as_assign_invalid_role(self):
        dynamic = {}
        ctx = {"is_command": True, "command": "as_assign",
               "message": "/as_assign 777 superuser"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
        assert result is not None
        assert "Unknown role" in result["reason"]
        assert "777" not in dynamic

    def test_as_revoke(self):
        dynamic = {"777": "user"}
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
        dynamic = {"123": "admin", "456": "user"}
        ctx = {"is_command": True, "command": "as_roles", "message": "/as_roles"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, dynamic)
        assert result is not None
        assert "123" in result["reason"]
        assert "456" in result["reason"]

    def test_as_info(self):
        ctx = {"is_command": True, "command": "as_info", "message": "/as_info 222"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "222" in result["reason"]
        assert "user" in result["reason"]

    def test_non_admin_command_returns_none(self):
        ctx = {"is_command": True, "command": "help", "message": "/help"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is None

    def test_non_command_returns_none(self):
        ctx = {"is_command": False, "message": "hello"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is None


# ---------------------------------------------------------------------------
# Full handle() integration
# ---------------------------------------------------------------------------

class TestHandleIntegration:
    @pytest.fixture
    def mock_config(self):
        with patch.object(h, "_load_config", return_value=SAMPLE_CONFIG), \
             patch.object(h, "_load_dynamic_roles", return_value={}), \
             patch.object(h, "_save_dynamic_roles"):
            yield

    @pytest.mark.asyncio
    async def test_owner_always_allowed(self, mock_config):
        ctx = {"chat_id": "999", "is_command": False, "message": "hello"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is True

    @pytest.mark.asyncio
    async def test_unlisted_allowed_when_deny_unlisted_false(self, mock_config):
        ctx = {"chat_id": "777", "is_command": False, "message": "hello"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is True

    @pytest.mark.asyncio
    async def test_unlisted_denied_when_deny_unlisted_true(self):
        config = {**SAMPLE_CONFIG, "deny_unlisted": True}
        with patch.object(h, "_load_config", return_value=config), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            ctx = {"chat_id": "777", "is_command": False, "message": "hello"}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is False
            assert "Unlisted denied" in result["reason"]

    @pytest.mark.asyncio
    async def test_user_chat_allowed(self, mock_config):
        ctx = {"chat_id": "222", "is_command": False, "message": "hello"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is True

    @pytest.mark.asyncio
    async def test_user_terminal_denied(self, mock_config):
        ctx = {"chat_id": "222", "is_command": True, "command": "terminal",
               "message": "/terminal ls"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is False
        assert "Action denied" in result["reason"]

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
                "user_id": "222",
                "message": "hello",
                "response": "hi there",
            }
            await h.handle("agent:end", ctx)
            log_file = tmp_hermes_home / "logs" / "conversations" / "222.jsonl"
            assert log_file.exists()
            entry = json.loads(log_file.read_text().strip())
            assert entry["user"] == "hello"
            assert entry["agent"] == "hi there"
            assert entry["role"] == "user"

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_after_threshold(self, mock_config):
        h._rate_state["222"] = {
            "minute": {"ts": time.time(), "count": 5},
            "day": {"ts": time.time(), "count": 5},
        }
        ctx = {"chat_id": "222", "is_command": False, "message": "hello"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is False
        assert "Rate limited (minute)" in result["reason"]
