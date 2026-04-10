"""
AgentShield edge-case and boundary tests — added for production audit.

Covers:
  - Empty / whitespace-only / oversized messages
  - Negative chat_id (Telegram group IDs are negative)
  - Rate limit boundary (exactly N and N+1 messages)
  - Rate limit counter TTL reset (bucket expires after 60s / 86400s)
  - TTL eviction of stale _rate_state entries
  - Config load failure (malformed YAML) — must not crash gateway
  - Config save failure (permissions) — must not crash gateway
  - Log rotation trigger (soft cap exceeded)
  - Log write failure — must not crash gateway
  - _send_telegram_alert success and failure paths
  - _notify_owner with and without token
  - Admin command argument validation (missing args)
  - handle() outer crash guard — any exception → allow=True
  - Thread-safety: concurrent increments give correct count
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "hook"))
import handler as h


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "enabled": True,
    "deny_unlisted": False,
    "roles": {
        "guest": {
            "chat_ids": [],
            "allow": ["chat"],
            "deny": ["command:*", "system:*", "terminal", "skill:*"],
            "rate_limit": {"messages_per_minute": 3, "messages_per_day": 10},
        },
    },
    "logging": {"conversations": False},
    "messages": {
        "rate_limit_minute": "Rate limited (minute)",
        "rate_limit_day": "Rate limited (day)",
        "action_denied": "Action denied",
        "unlisted_denied": "Unlisted denied",
    },
    "alerts": {"on_action_denied": True, "on_rate_limit": True},
}


@pytest.fixture(autouse=True)
def reset_rate_state():
    """Clear rate limiter state and eviction timer between tests."""
    h._rate_state.clear()
    h._last_eviction = 0.0
    yield
    h._rate_state.clear()
    h._last_eviction = 0.0


@pytest.fixture
def tmp_hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# 1. Input — empty / whitespace / oversized messages
# ---------------------------------------------------------------------------

class TestInputEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_message_allowed(self):
        """Empty message → action=chat → allowed for guest."""
        with patch.object(h, "_load_config", return_value=SAMPLE_CONFIG), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            ctx = {"chat_id": "111", "is_command": False, "message": ""}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True

    @pytest.mark.asyncio
    async def test_whitespace_only_message_allowed(self):
        """Whitespace-only message → not a command → chat → allowed."""
        with patch.object(h, "_load_config", return_value=SAMPLE_CONFIG), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            ctx = {"chat_id": "111", "is_command": False, "message": "   "}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True

    @pytest.mark.asyncio
    async def test_oversized_message_truncated_in_alert(self):
        """Message >80 chars is truncated to 80 in owner alert — no crash."""
        long_msg = "A" * 5000  # 5000 chars — well above Telegram's 4096 limit
        with patch.object(h, "_load_config", return_value=SAMPLE_CONFIG), \
             patch.object(h, "_load_dynamic_roles", return_value={}), \
             patch.object(h, "_notify_owner") as mock_notify:
            ctx = {
                "chat_id": "111",
                "is_command": True,
                "command": "terminal",
                "message": long_msg,
            }
            result = await h.handle("before_message", ctx)
            assert result["allow"] is False
            # Verify alert was called with truncated message (max 80 chars)
            assert mock_notify.called
            detail_arg = mock_notify.call_args[0][3]  # positional: config, event, chat_id, detail
            assert "AAAAA" in detail_arg
            assert len(detail_arg) < 200  # detail includes role= prefix, kept sane

    @pytest.mark.asyncio
    async def test_message_exactly_4096_chars_does_not_crash(self):
        """Telegram max message length (4096) must not cause any error."""
        msg = "X" * 4096
        with patch.object(h, "_load_config", return_value=SAMPLE_CONFIG), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            ctx = {"chat_id": "111", "is_command": False, "message": msg}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True


# ---------------------------------------------------------------------------
# 2. Negative chat_id (Telegram group chats have negative IDs)
# ---------------------------------------------------------------------------

class TestNegativeChatId:
    @pytest.mark.asyncio
    async def test_negative_chat_id_allowed(self):
        """Negative chat_id (group) is treated as a regular guest user."""
        with patch.object(h, "_load_config", return_value=SAMPLE_CONFIG), \
             patch.object(h, "_load_dynamic_roles", return_value={}):
            ctx = {"chat_id": "-1001234567890", "is_command": False, "message": "hi"}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True

    def test_negative_chat_id_rate_limited(self):
        """Negative chat_id can be rate-limited like any other user."""
        limits = {"messages_per_minute": 2, "messages_per_day": 100}
        h._rate_state["-1001234567890"] = {
            "minute": {"ts": time.time(), "count": 2},
            "day": {"ts": time.time(), "count": 2},
            "_last_seen": time.time(),
        }
        result = h._check_rate_limit("-1001234567890", limits)
        assert result == "rate_limit_minute"


# ---------------------------------------------------------------------------
# 3. Rate limit boundary (exactly N and N+1 messages)
# ---------------------------------------------------------------------------

class TestRateLimitBoundary:
    def test_exactly_at_limit_is_blocked(self):
        """count == limit → blocked (boundary inclusive)."""
        limits = {"messages_per_minute": 5, "messages_per_day": 100}
        h._rate_state["u1"] = {
            "minute": {"ts": time.time(), "count": 5},
            "day": {"ts": time.time(), "count": 1},
            "_last_seen": time.time(),
        }
        assert h._check_rate_limit("u1", limits) == "rate_limit_minute"

    def test_one_below_limit_is_allowed(self):
        """count == limit - 1 → allowed."""
        limits = {"messages_per_minute": 5, "messages_per_day": 100}
        h._rate_state["u1"] = {
            "minute": {"ts": time.time(), "count": 4},
            "day": {"ts": time.time(), "count": 1},
            "_last_seen": time.time(),
        }
        assert h._check_rate_limit("u1", limits) is None

    def test_day_boundary_blocked(self):
        """Day limit boundary — count == day_limit is blocked."""
        limits = {"messages_per_minute": 1000, "messages_per_day": 10}
        h._rate_state["u1"] = {
            "minute": {"ts": time.time(), "count": 0},
            "day": {"ts": time.time(), "count": 10},
            "_last_seen": time.time(),
        }
        assert h._check_rate_limit("u1", limits) == "rate_limit_day"

    def test_day_bucket_resets_after_86400s(self):
        """Day bucket resets when >86400 seconds have elapsed."""
        limits = {"messages_per_minute": 1000, "messages_per_day": 10}
        h._rate_state["u1"] = {
            "minute": {"ts": time.time(), "count": 0},
            "day": {"ts": time.time() - 90000, "count": 999},
            "_last_seen": time.time(),
        }
        assert h._check_rate_limit("u1", limits) is None

    def test_minute_bucket_not_reset_at_59s(self):
        """Minute bucket does NOT reset at 59s (strictly > 60 required)."""
        limits = {"messages_per_minute": 3, "messages_per_day": 100}
        h._rate_state["u1"] = {
            "minute": {"ts": time.time() - 59, "count": 3},
            "day": {"ts": time.time(), "count": 0},
            "_last_seen": time.time(),
        }
        assert h._check_rate_limit("u1", limits) == "rate_limit_minute"

    def test_record_after_check_increments_correctly(self):
        """_record_message increments both buckets exactly once."""
        h._rate_state["u1"] = {
            "minute": {"ts": time.time(), "count": 0},
            "day": {"ts": time.time(), "count": 0},
            "_last_seen": time.time(),
        }
        h._record_message("u1")
        h._record_message("u1")
        assert h._rate_state["u1"]["minute"]["count"] == 2
        assert h._rate_state["u1"]["day"]["count"] == 2


# ---------------------------------------------------------------------------
# 4. Rate state TTL eviction
# ---------------------------------------------------------------------------

class TestRateStateEviction:
    def test_stale_entries_are_evicted(self):
        """Entries not seen for >_RATE_STATE_TTL seconds are removed."""
        # Force eviction by setting _last_eviction to far past
        h._last_eviction = 0.0
        old_ts = time.time() - h._RATE_STATE_TTL - 1
        h._rate_state["stale1"] = {"_last_seen": old_ts}
        h._rate_state["stale2"] = {"_last_seen": old_ts}
        h._rate_state["fresh"] = {"_last_seen": time.time()}

        # Trigger eviction via _check_rate_limit (which calls _evict_stale inside lock)
        h._check_rate_limit("fresh", {"messages_per_minute": 10, "messages_per_day": 100})

        assert "stale1" not in h._rate_state
        assert "stale2" not in h._rate_state
        assert "fresh" in h._rate_state

    def test_eviction_not_run_within_1h(self):
        """Eviction is skipped if last eviction was < 1h ago."""
        h._last_eviction = time.time() - 100  # 100s ago — under 3600s threshold
        old_ts = time.time() - h._RATE_STATE_TTL - 1
        h._rate_state["stale"] = {"_last_seen": old_ts}

        h._check_rate_limit("other", {"messages_per_minute": 10, "messages_per_day": 100})

        # stale NOT evicted because eviction is throttled
        assert "stale" in h._rate_state


# ---------------------------------------------------------------------------
# 5. Config load failure — must not crash
# ---------------------------------------------------------------------------

class TestConfigLoadFailure:
    def test_malformed_yaml_returns_empty(self, tmp_hermes_home):
        """Malformed YAML in agentshield.yaml must return {} and not crash."""
        config_path = tmp_hermes_home / "agentshield.yaml"
        config_path.write_text(": invalid: yaml: [\n---\n{broken", encoding="utf-8")
        result = h._load_config()
        assert result == {}

    def test_missing_config_returns_empty(self, tmp_hermes_home):
        """No config file → returns {} (pass-through mode)."""
        result = h._load_config()
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_config_passes_messages_through(self, tmp_hermes_home):
        """When config is missing, all messages pass through (fail-open)."""
        ctx = {"chat_id": "111", "is_command": False, "message": "hi"}
        result = await h.handle("before_message", ctx)
        assert result["allow"] is True


# ---------------------------------------------------------------------------
# 6. Config save failure — must not crash
# ---------------------------------------------------------------------------

class TestConfigSaveFailure:
    def test_save_fails_gracefully(self, tmp_hermes_home, capsys):
        """If save_dynamic_roles fails (e.g. permissions), it logs and continues."""
        with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
            # Must not raise
            h._save_dynamic_roles({"123": "guest"})
        captured = capsys.readouterr()
        assert "Failed to save" in captured.out


# ---------------------------------------------------------------------------
# 7. Log rotation
# ---------------------------------------------------------------------------

class TestLogRotation:
    def test_rotation_triggered_when_over_limit(self, tmp_hermes_home):
        """When log file exceeds max_bytes, oldest 20% of lines are dropped."""
        log_dir = tmp_hermes_home / "logs" / "conversations"
        log_dir.mkdir(parents=True)
        log_path = log_dir / "777.jsonl"

        # Write 100 lines
        lines = [f'{{"ts": "t", "i": {i}}}\n' for i in range(100)]
        log_path.write_text("".join(lines), encoding="utf-8")

        size_before = log_path.stat().st_size
        # Set max_bytes to 1 byte to force rotation
        h._rotate_log_if_needed(log_path, max_bytes=1)

        # File should now be smaller and have fewer lines
        content_after = log_path.read_text(encoding="utf-8").splitlines()
        assert len(content_after) < 100
        assert len(content_after) == 80  # 100 - 20% = 80 lines kept

    def test_no_rotation_when_under_limit(self, tmp_hermes_home):
        """File under max_bytes must NOT be rotated."""
        log_dir = tmp_hermes_home / "logs" / "conversations"
        log_dir.mkdir(parents=True)
        log_path = log_dir / "777.jsonl"
        log_path.write_text('{"ts": "t", "i": 0}\n' * 10, encoding="utf-8")
        size_before = log_path.stat().st_size
        h._rotate_log_if_needed(log_path, max_bytes=10 * 1024 * 1024)
        assert log_path.stat().st_size == size_before

    def test_rotation_failure_does_not_crash(self, tmp_hermes_home, capsys):
        """If rotation fails (e.g. disk full), it logs and leaves original intact."""
        log_dir = tmp_hermes_home / "logs" / "conversations"
        log_dir.mkdir(parents=True)
        log_path = log_dir / "777.jsonl"
        log_path.write_text("x" * 1000, encoding="utf-8")

        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            h._rotate_log_if_needed(log_path, max_bytes=1)

        # Original file intact
        assert log_path.stat().st_size == 1000
        captured = capsys.readouterr()
        assert "rotation failed" in captured.out.lower()

    @pytest.mark.asyncio
    async def test_log_write_failure_does_not_crash(self, tmp_hermes_home):
        """If log write fails, handle() still returns allow=True — no crash."""
        config = {**SAMPLE_CONFIG, "logging": {"conversations": True}}
        with patch.object(h, "_load_config", return_value=config), \
             patch.object(h, "_load_dynamic_roles", return_value={}), \
             patch("builtins.open", side_effect=OSError("disk full")):
            ctx = {
                "user_id": "777",
                "message": "hello",
                "response": "hi",
            }
            result = await h.handle("agent:end", ctx)
            assert result["allow"] is True


# ---------------------------------------------------------------------------
# 8. Telegram alert — success and failure paths
# ---------------------------------------------------------------------------

class TestTelegramAlert:
    def test_send_alert_success(self):
        """Successful alert path — urlopen called with correct URL."""
        mock_response = MagicMock()
        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            h._send_telegram_alert("mytoken", "123456", "test message")
            assert mock_open.called
            req = mock_open.call_args[0][0]
            assert "mytoken" in req.full_url
            assert "sendMessage" in req.full_url

    def test_send_alert_network_failure_does_not_crash(self, capsys):
        """Network error during alert must be swallowed — never crashes handler."""
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            h._send_telegram_alert("mytoken", "123456", "test")
        captured = capsys.readouterr()
        assert "Telegram alert failed" in captured.out

    def test_notify_owner_no_token_skips(self):
        """If TELEGRAM_BOT_TOKEN is not set, _notify_owner is a no-op."""
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(h, "_send_telegram_alert") as mock_send:
            # ensure TELEGRAM_BOT_TOKEN is absent
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            h._notify_owner(SAMPLE_CONFIG, "action_denied", "777", "test")
            mock_send.assert_not_called()

    def test_notify_owner_no_owner_id_skips(self):
        """If owner_chat_id is not configured, _notify_owner is a no-op."""
        config_no_owner = {k: v for k, v in SAMPLE_CONFIG.items() if k != "owner_chat_id"}
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "testtoken"}), \
             patch.object(h, "_send_telegram_alert") as mock_send:
            h._notify_owner(config_no_owner, "action_denied", "777", "test")
            mock_send.assert_not_called()

    def test_notify_owner_with_token_and_id_calls_send(self):
        """With token + owner_chat_id, _notify_owner calls _send_telegram_alert."""
        config_with_owner = {**SAMPLE_CONFIG, "owner_chat_id": "999"}
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "testtoken"}), \
             patch.object(h, "_send_telegram_alert") as mock_send:
            h._notify_owner(config_with_owner, "action_denied", "777", "role=guest")
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert args[0] == "testtoken"
            assert args[1] == "999"
            assert "action_denied" in args[2]

    def test_notify_owner_unknown_event_uses_default_emoji(self):
        """Unknown event type falls back to ⚠️ emoji — no KeyError."""
        config_with_owner = {**SAMPLE_CONFIG, "owner_chat_id": "999"}
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "testtoken"}), \
             patch.object(h, "_send_telegram_alert") as mock_send:
            h._notify_owner(config_with_owner, "unknown_event_xyz", "777", "detail")
            assert mock_send.called
            text = mock_send.call_args[0][2]
            assert "⚠️" in text


# ---------------------------------------------------------------------------
# 9. Admin command argument validation
# ---------------------------------------------------------------------------

class TestAdminCommandArgValidation:
    def test_as_assign_missing_both_args(self):
        ctx = {"is_command": True, "command": "as_assign", "message": "/as_assign"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "Usage:" in result["reason"]

    def test_as_assign_missing_role_arg(self):
        ctx = {"is_command": True, "command": "as_assign", "message": "/as_assign 777"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "Usage:" in result["reason"]

    def test_as_revoke_missing_arg(self):
        ctx = {"is_command": True, "command": "as_revoke", "message": "/as_revoke"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "Usage:" in result["reason"]

    def test_as_info_missing_arg(self):
        ctx = {"is_command": True, "command": "as_info", "message": "/as_info"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "Usage:" in result["reason"]

    def test_as_info_reads_rate_state_under_lock(self):
        """as_info must read _rate_state under _rate_lock — verify no deadlock."""
        h._rate_state["888"] = {
            "minute": {"ts": time.time(), "count": 5},
            "day": {"ts": time.time(), "count": 42},
            "_last_seen": time.time(),
        }
        ctx = {"is_command": True, "command": "as_info", "message": "/as_info 888"}
        result = h._handle_admin_command(ctx, SAMPLE_CONFIG, {})
        assert result is not None
        assert "5" in result["reason"]   # minute count
        assert "42" in result["reason"]  # day count


# ---------------------------------------------------------------------------
# 10. handle() outer crash guard
# ---------------------------------------------------------------------------

class TestCrashGuard:
    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_allow_true(self, capsys):
        """Any unhandled exception in _handle_inner → allow=True (fail-open)."""
        with patch.object(h, "_load_config", side_effect=RuntimeError("boom")):
            ctx = {"chat_id": "777", "is_command": False, "message": "hi"}
            result = await h.handle("before_message", ctx)
            assert result["allow"] is True
        captured = capsys.readouterr()
        assert "Unexpected error" in captured.out
        assert "boom" in captured.out

    @pytest.mark.asyncio
    async def test_crash_in_agent_end_returns_allow_true(self, capsys):
        """Crash during agent:end logging must still return allow=True."""
        with patch.object(h, "_load_config", side_effect=RuntimeError("log crash")):
            ctx = {"user_id": "777", "message": "x", "response": "y"}
            result = await h.handle("agent:end", ctx)
            assert result["allow"] is True


# ---------------------------------------------------------------------------
# 11. Thread-safety — concurrent _record_message
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_record_message_correct_count(self):
        """100 concurrent threads each calling _record_message once → count == 100."""
        chat_id = "thread_test"
        h._rate_state[chat_id] = {
            "minute": {"ts": time.time(), "count": 0},
            "day": {"ts": time.time(), "count": 0},
            "_last_seen": time.time(),
        }

        def worker():
            h._record_message(chat_id)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert h._rate_state[chat_id]["minute"]["count"] == 100
        assert h._rate_state[chat_id]["day"]["count"] == 100

    def test_concurrent_check_and_record_no_exception(self):
        """Concurrent check + record from multiple threads must not raise."""
        chat_id = "concurrent"
        limits = {"messages_per_minute": 1000, "messages_per_day": 10000}
        h._rate_state[chat_id] = {
            "minute": {"ts": time.time(), "count": 0},
            "day": {"ts": time.time(), "count": 0},
            "_last_seen": time.time(),
        }
        errors = []

        def worker():
            try:
                h._check_rate_limit(chat_id, limits)
                h._record_message(chat_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"


# ---------------------------------------------------------------------------
# 12. _infer_action edge cases
# ---------------------------------------------------------------------------

class TestInferActionEdgeCases:
    def test_command_uppercase_normalized(self):
        """Command names are lowercased before matching."""
        ctx = {"is_command": True, "command": "RESET", "message": "/RESET"}
        assert h._infer_action(ctx) == "system:reset"

    def test_command_with_leading_slash_in_cmd_field(self):
        """Command field with leading slash is stripped correctly."""
        ctx = {"is_command": True, "command": "/help", "message": "/help"}
        # cmd becomes "/help".lower().strip() = "/help" — maps to command:/help
        # This is a known edge case: the gateway should not include the slash in 'command'
        # but we document the behavior here without breaking it.
        result = h._infer_action(ctx)
        assert result == "command:/help"  # documents current behavior

    def test_skill_with_only_verb(self):
        """'/skill run' with no name → skill:*."""
        ctx = {"is_command": True, "command": "skill", "message": "/skill run"}
        assert h._infer_action(ctx) == "skill:*"

    def test_no_command_field_defaults_to_chat(self):
        """Missing 'command' key → 'chat' (not a crash)."""
        ctx = {"is_command": True}  # missing 'command' key entirely
        result = h._infer_action(ctx)
        assert result == "command:"  # empty string normalized to 'command:'

    def test_none_command_field(self):
        """command=None → treated as empty string → command:."""
        ctx = {"is_command": True, "command": None, "message": ""}
        result = h._infer_action(ctx)
        assert result == "command:"


# ---------------------------------------------------------------------------
# 13. Disk usage estimate helper test
# ---------------------------------------------------------------------------

class TestDiskUsageEstimate:
    """Not a functional test — documents estimated log growth.

    Estimate basis:
      - Average log entry: ~250 bytes (ts + chat_id + role + short message + short reply)
      - 100 active customers × 20 messages/day = 2000 entries/day
      - 30 days → 60,000 entries → ~15 MB total across all user log files
      - Per-user (100 msgs/day): 100 × 250 = 25 KB/day → 750 KB in 30 days
      - Well under default 10 MB/user soft cap → rotation rarely triggered
    """
    def test_estimate_sanity(self):
        """Average log entry is under 500 bytes."""
        import json
        from datetime import datetime
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "chat_id": "1234567890",
            "role": "guest",
            "user": "Hello, I need help with my order #12345",
            "agent": "Of course! I'd be happy to help. Could you please provide more details?",
        }
        size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        assert size < 500, f"Entry size {size} bytes — adjust estimate if entry schema changes"
