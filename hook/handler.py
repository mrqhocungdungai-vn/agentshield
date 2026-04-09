"""
AgentShield — Hermes before_message hook  (v0.2.0)
====================================================
Role-based access control middleware for Hermes Gateway.

Features
--------
- Per-role allow / deny lists with wildcard patterns (fnmatch)
- Per-role rate limiting  (messages per minute + messages per day)
- Action inference from message context (chat / command:x / skill:x / system:*)
- Persistent role assignments  →  ~/.hermes/agentshield_roles.json
- Per-user conversation logging → ~/.hermes/logs/conversations/<chat_id>.jsonl
- Owner /admin commands for runtime role management:
    /as_assign <chat_id> <role>
    /as_revoke <chat_id>
    /as_roles
    /as_info <chat_id>

Config file: ~/.hermes/agentshield.yaml

Config format
-------------
agentshield:
  enabled: true

  # Owner chat_id — always bypasses all checks and can run /admin commands
  owner_chat_id: "123456789"

  # If true, users NOT listed in any role get denied.
  # If false (default), unlisted users pass through (Hermes owns the allowlist).
  deny_unlisted: false

  roles:
    admin:
      chat_ids: ["111111111"]
      allow: ["*"]
      rate_limit:
        messages_per_minute: 60
        messages_per_day: 2000

    user:
      chat_ids: ["222222222"]
      allow: ["chat", "skill:*", "command:help", "command:new", "command:reset"]
      deny: ["terminal", "system:stop"]
      rate_limit:
        messages_per_minute: 10
        messages_per_day: 200

    guest:
      chat_ids: []
      allow: ["chat"]
      rate_limit:
        messages_per_minute: 3
        messages_per_day: 30

  logging:
    conversations: true   # log every turn to ~/.hermes/logs/conversations/

  messages:
    rate_limit_minute: "⏳ Bạn gửi tin nhắn quá nhanh. Vui lòng chờ 1 phút."
    rate_limit_day: "📵 Bạn đã đạt giới hạn tin nhắn hôm nay. Thử lại vào ngày mai."
    action_denied: "🚫 Bạn không có quyền thực hiện hành động này."
    unlisted_denied: "❌ Bạn chưa được cấp quyền truy cập agent này."
"""

from __future__ import annotations

import fnmatch
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _roles_file() -> Path:
    return _hermes_home() / "agentshield_roles.json"


def _conv_log_dir() -> Path:
    return _hermes_home() / "logs" / "conversations"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config() -> Dict[str, Any]:
    """Load agentshield.yaml from ~/.hermes/ or hook dir."""
    candidates = [
        _hermes_home() / "agentshield.yaml",
        Path(__file__).parent / "config.yaml",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return data.get("agentshield", data)
            except Exception as e:
                print(f"[agentshield] Failed to load config {path}: {e}", flush=True)
    return {}


# ---------------------------------------------------------------------------
# Role persistence
# ---------------------------------------------------------------------------

def _load_dynamic_roles() -> Dict[str, str]:
    """Load dynamically-assigned roles from disk. Returns {chat_id: role_name}."""
    path = _roles_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[agentshield] Failed to load role assignments: {e}", flush=True)
        return {}


def _save_dynamic_roles(assignments: Dict[str, str]) -> None:
    """Persist role assignments to disk atomically."""
    path = _roles_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(assignments, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        print(f"[agentshield] Failed to save role assignments: {e}", flush=True)


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per gateway process)
# ---------------------------------------------------------------------------

# {chat_id: {"minute": {"ts": float, "count": int}, "day": {"ts": float, "count": int}}}
_rate_state: Dict[str, Dict[str, Any]] = {}


def _check_rate_limit(chat_id: str, limits: Dict[str, int]) -> Optional[str]:
    """
    Check rate limits. Returns None if OK, or a message key if exceeded.
    Does NOT increment counters — call _record_message() after allowing.
    """
    now = time.time()
    state = _rate_state.setdefault(chat_id, {})

    per_min = limits.get("messages_per_minute")
    if per_min:
        bucket = state.setdefault("minute", {"ts": now, "count": 0})
        if now - bucket["ts"] > 60:
            bucket["ts"] = now
            bucket["count"] = 0
        if bucket["count"] >= per_min:
            return "rate_limit_minute"

    per_day = limits.get("messages_per_day")
    if per_day:
        bucket = state.setdefault("day", {"ts": now, "count": 0})
        if now - bucket["ts"] > 86400:
            bucket["ts"] = now
            bucket["count"] = 0
        if bucket["count"] >= per_day:
            return "rate_limit_day"

    return None


def _record_message(chat_id: str) -> None:
    """Increment rate counters after a message is allowed through."""
    state = _rate_state.get(chat_id, {})
    for bucket_name in ("minute", "day"):
        bucket = state.get(bucket_name)
        if bucket:
            bucket["count"] += 1


# ---------------------------------------------------------------------------
# Action inference
# ---------------------------------------------------------------------------

def _infer_action(context: Dict[str, Any]) -> str:
    """
    Infer the AgentShield action name from message context.

    Conventions:
      "chat"           — regular text message
      "command:<name>" — slash command  (/help → "command:help")
      "skill:<name>"   — /skill run <name> invocation
      "system:reset"   — /reset, /new, /clear
      "system:stop"    — /stop, /cancel
      "terminal"       — reserved for future shell-command detection
    """
    if not context.get("is_command"):
        return "chat"

    cmd = (context.get("command") or "").lower().strip()

    if cmd in {"reset", "new", "clear"}:
        return "system:reset"
    if cmd in {"stop", "cancel"}:
        return "system:stop"
    if cmd == "skill":
        message = context.get("message", "")
        parts = message.strip().lstrip("/").split()
        skill_name = parts[2] if len(parts) > 2 else "*"
        return f"skill:{skill_name}"

    return f"command:{cmd}"


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

def _find_role(
    chat_id: str,
    config: Dict[str, Any],
    dynamic: Dict[str, str],
) -> Optional[str]:
    """
    Resolve the role for a chat_id. Priority order:
    1. Owner (from config)
    2. Dynamic assignment (from agentshield_roles.json)
    3. Static assignment (from config chat_ids)
    4. None (unlisted)
    """
    owner_id = str(config.get("owner_chat_id", ""))
    if owner_id and chat_id == owner_id:
        return "owner"

    # Dynamic first (allows runtime promotion/demotion)
    if chat_id in dynamic:
        return dynamic[chat_id]

    # Static from config
    roles = config.get("roles", {})
    for role_name, role_cfg in roles.items():
        chat_ids: List[str] = [str(x) for x in (role_cfg.get("chat_ids") or [])]
        if chat_id in chat_ids:
            return role_name

    return None


# ---------------------------------------------------------------------------
# Permission check
# ---------------------------------------------------------------------------

def _is_action_allowed(action: str, role_cfg: Dict[str, Any]) -> bool:
    """
    Check if action is allowed by role's allow/deny lists.
    Logic: deny overrides allow. Default-deny if allow list is non-empty.
    """
    allow_patterns: List[str] = role_cfg.get("allow", [])
    deny_patterns: List[str] = role_cfg.get("deny", [])

    for pattern in deny_patterns:
        if fnmatch.fnmatch(action, pattern):
            return False

    for pattern in allow_patterns:
        if fnmatch.fnmatch(action, pattern):
            return True

    # Empty allow list = no restrictions defined = allow
    return len(allow_patterns) == 0


# ---------------------------------------------------------------------------
# Conversation logging
# ---------------------------------------------------------------------------

def _log_conversation(
    config: Dict[str, Any],
    chat_id: str,
    role: str,
    user_msg: str,
    agent_reply: str,
) -> None:
    """Append one conversation turn to ~/.hermes/logs/conversations/<chat_id>.jsonl"""
    logging_cfg = config.get("logging", {})
    if not logging_cfg.get("conversations", True):
        return
    try:
        log_dir = _conv_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "chat_id": chat_id,
            "role": role,
            "user": user_msg,
            "agent": agent_reply,
        }
        with open(log_dir / f"{chat_id}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[agentshield] Conversation log failed: {e}", flush=True)


# ---------------------------------------------------------------------------
# Admin command handler
# ---------------------------------------------------------------------------

_ADMIN_COMMANDS = {"as_assign", "as_revoke", "as_roles", "as_info"}


def _handle_admin_command(
    context: Dict[str, Any],
    config: Dict[str, Any],
    dynamic: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """
    Process owner-only admin commands. Returns a block response with the result,
    or None if the message is not an admin command.

    Commands:
      /as_assign <chat_id> <role>  — assign a role dynamically
      /as_revoke <chat_id>         — remove dynamic assignment (fall back to config)
      /as_roles                    — list all dynamic assignments
      /as_info <chat_id>           — show role + rate state for a user
    """
    if not context.get("is_command"):
        return None

    cmd = (context.get("command") or "").lower().strip()
    if cmd not in _ADMIN_COMMANDS:
        return None

    # Parse args from the raw message
    message = context.get("message", "")
    parts = message.strip().split()
    # parts[0] is the command itself (e.g. "/as_assign")
    args = parts[1:]

    valid_roles = set(config.get("roles", {}).keys()) | {"owner"}

    if cmd == "as_assign":
        if len(args) < 2:
            reply = "Usage: /as_assign <chat_id> <role>\nValid roles: " + ", ".join(sorted(valid_roles))
        else:
            target_id, role_name = str(args[0]), args[1].lower()
            if role_name not in valid_roles:
                reply = f"Unknown role: {role_name}\nValid roles: {', '.join(sorted(valid_roles))}"
            else:
                dynamic[target_id] = role_name
                _save_dynamic_roles(dynamic)
                reply = f"✅ Assigned role '{role_name}' to chat_id {target_id}"

    elif cmd == "as_revoke":
        if len(args) < 1:
            reply = "Usage: /as_revoke <chat_id>"
        else:
            target_id = str(args[0])
            if target_id in dynamic:
                removed_role = dynamic.pop(target_id)
                _save_dynamic_roles(dynamic)
                reply = f"✅ Revoked dynamic role '{removed_role}' from {target_id}"
            else:
                reply = f"No dynamic role found for {target_id}"

    elif cmd == "as_roles":
        if not dynamic:
            reply = "No dynamic role assignments."
        else:
            lines = [f"Dynamic role assignments ({len(dynamic)}):"]
            for cid, role in sorted(dynamic.items()):
                lines.append(f"  {cid} → {role}")
            reply = "\n".join(lines)

    elif cmd == "as_info":
        if len(args) < 1:
            reply = "Usage: /as_info <chat_id>"
        else:
            target_id = str(args[0])
            role = _find_role(target_id, config, dynamic)
            rate_info = _rate_state.get(target_id, {})
            min_count = rate_info.get("minute", {}).get("count", 0)
            day_count = rate_info.get("day", {}).get("count", 0)
            reply = (
                f"chat_id: {target_id}\n"
                f"role: {role or 'unlisted'}\n"
                f"messages this minute: {min_count}\n"
                f"messages today: {day_count}"
            )
    else:
        return None

    # Block the message from reaching the agent, send the admin reply instead
    return {"allow": False, "reason": reply}


# ---------------------------------------------------------------------------
# Main handler — before_message
# ---------------------------------------------------------------------------

async def handle(event_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    AgentShield gateway hook handler.

    before_message: enforce RBAC + rate limits, handle admin commands.
    agent:end: log conversation turn.

    Returns:
        {"allow": True}                     — message proceeds to agent
        {"allow": False, "reason": "..."}   — blocked, reason sent to user
    """

    # ── agent:end → log conversation ──────────────────────────────────────
    if event_type == "agent:end":
        config = _load_config()
        if config and config.get("enabled", True):
            chat_id = str(context.get("user_id") or context.get("chat_id") or "")
            dynamic = _load_dynamic_roles()
            role = _find_role(chat_id, config, dynamic) or "unknown"
            _log_conversation(
                config,
                chat_id,
                role,
                context.get("message", ""),
                context.get("response", ""),
            )
        return {"allow": True}

    # ── before_message ─────────────────────────────────────────────────────
    config = _load_config()

    # Disabled or no config → pass through
    if not config or not config.get("enabled", True):
        return {"allow": True}

    chat_id = str(context.get("chat_id") or context.get("user_id") or "")
    if not chat_id:
        return {"allow": True}

    dynamic = _load_dynamic_roles()
    role = _find_role(chat_id, config, dynamic)
    messages = config.get("messages", {})

    # ── Owner: check for admin commands first, then always allow ──────────
    if role == "owner":
        admin_result = _handle_admin_command(context, config, dynamic)
        if admin_result is not None:
            return admin_result
        _record_message(chat_id)
        return {"allow": True}

    # ── Unlisted user ──────────────────────────────────────────────────────
    if role is None:
        if config.get("deny_unlisted", False):
            reason = messages.get("unlisted_denied", "You don't have access to this agent.")
            return {"allow": False, "reason": reason}
        return {"allow": True}

    # ── Known role — rate limit check ─────────────────────────────────────
    role_cfg = config.get("roles", {}).get(role, {})
    rate_limits = role_cfg.get("rate_limit", {})
    if rate_limits:
        limit_key = _check_rate_limit(chat_id, rate_limits)
        if limit_key:
            reason = messages.get(limit_key, "Rate limit exceeded. Please try again later.")
            return {"allow": False, "reason": reason}

    # ── Action permission check ───────────────────────────────────────────
    action = _infer_action(context)
    if not _is_action_allowed(action, role_cfg):
        reason = messages.get("action_denied", "You don't have permission to do that.")
        return {"allow": False, "reason": reason}

    # ── All checks passed ─────────────────────────────────────────────────
    _record_message(chat_id)
    return {"allow": True}
