"""
AgentShield — Hermes before_message hook  (v0.3.0)
====================================================
Role-based access control middleware for Hermes Gateway.

Two-role model
--------------
- guest  (active)  — all external/unknown users. Rate-limited, action-controlled,
                     conversation-logged. This is the only enforced role.
- owner  (planned) — reserved. See # TODO: owner role below.

Features
--------
- Auto-guest: all users fall into guest by default — no whitelist needed
- Per-role rate limiting  (messages per minute + messages per day)
- Action inference from message context (chat / command:x / skill:x / system:*)
- Per-role allow/deny lists with wildcard patterns (fnmatch)
- Persistent role assignments  →  ~/.hermes/agentshield_roles.json
- Per-user conversation logging → ~/.hermes/logs/conversations/<chat_id>.jsonl
- Owner alerts via Telegram Bot API on action_denied / rate_limit events

Config file: ~/.hermes/agentshield.yaml

Config format
-------------
agentshield:
  enabled: true

  # TODO: owner role — set owner_chat_id here when owner bypass is implemented.
  # owner_chat_id: "123456789"

  deny_unlisted: false   # false = everyone gets guest. true = block unknown users.

  roles:
    guest:
      chat_ids: []        # not used for guest (all unknown users → guest)
      allow: ["chat"]
      deny: ["command:*", "system:*", "terminal", "skill:*"]
      rate_limit:
        messages_per_minute: 10
        messages_per_day: 200

  alerts:
    on_action_denied: true
    on_rate_limit: false

  logging:
    conversations: true   # log every turn to ~/.hermes/logs/conversations/

  messages:
    rate_limit_minute: "I'm handling a lot of messages right now — please try again in a moment 😊"
    rate_limit_day: "You've reached today's message limit. Feel free to continue tomorrow!"
    action_denied: "That feature isn't available in this chat. Please contact our support team 😊"
    unlisted_denied: "You do not have access to this agent."
"""

from __future__ import annotations

import fnmatch
import json
import os
import time
import urllib.request
import urllib.parse
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
# Telegram alert helper
# ---------------------------------------------------------------------------

def _send_telegram_alert(token: str, chat_id: str, text: str) -> None:
    """Send a message to owner via Telegram Bot API (stdlib only, no httpx)."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[agentshield] Telegram alert failed: {e}", flush=True)


def _notify_owner(config: Dict[str, Any], event: str, chat_id: str, detail: str) -> None:
    """Send security alert to owner if bot token is available."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    owner_id = str(config.get("owner_chat_id", ""))
    if not token or not owner_id:
        return
    emoji_map = {
        "action_denied": "🚫",
        "rate_limit_minute": "⏳",
        "rate_limit_day": "📵",
    }
    emoji = emoji_map.get(event, "⚠️")
    text = (
        f"{emoji} <b>AgentShield Alert</b>\n"
        f"Event: <code>{event}</code>\n"
        f"User: <code>{chat_id}</code>\n"
        f"Detail: {detail}"
    )
    _send_telegram_alert(token, owner_id, text)


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
# Role resolution — 2-role model
# ---------------------------------------------------------------------------

def _find_role(
    chat_id: str,
    config: Dict[str, Any],
    dynamic: Dict[str, str],
) -> Optional[str]:
    """
    Resolve the role for a chat_id.

    Two-role model:
      - "owner"  → reserved / planned (see TODO below)
      - "guest"  → all other users (active, enforced)
      - None     → unlisted (only when deny_unlisted=true)

    Priority order:
      1. Owner check (by config owner_chat_id)
      2. Dynamic assignment (from agentshield_roles.json)
      3. None (unlisted — caller falls back to guest unless deny_unlisted)

    Note: static chat_ids per-role (admin/user) have been removed.
    The only meaningful static assignment is owner_chat_id in config.
    """
    # TODO: owner role — check owner_chat_id from config.
    # When owner bypass is implemented, this block will short-circuit
    # all further checks and return "owner" for the owner's chat_id.
    # For now, owner is not identified — they interact via CLI, not Telegram.
    owner_id = str(config.get("owner_chat_id", ""))
    if owner_id and chat_id == owner_id:
        # TODO: owner role — return "owner" and bypass all checks in handle().
        # Temporarily falls through to guest treatment below.
        pass

    # Dynamic assignment (runtime /as_assign commands)
    if chat_id in dynamic:
        return dynamic[chat_id]

    # All other users are unlisted — caller decides guest vs deny
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
      /as_revoke <chat_id>         — remove dynamic assignment
      /as_roles                    — list all dynamic assignments
      /as_info <chat_id>           — show role + rate state for a user

    Valid roles in the 2-role model: guest only.
    (owner is reserved but not assignable via /as_assign — it is a config-level concept.)
    """
    if not context.get("is_command"):
        return None

    cmd = (context.get("command") or "").lower().strip()
    if cmd not in _ADMIN_COMMANDS:
        return None

    # Parse args from the raw message
    message = context.get("message", "")
    parts = message.strip().split()
    args = parts[1:]

    # Valid assignable roles: only guest in the 2-role model.
    # owner is intentionally excluded — it is set via config, not /as_assign.
    valid_roles = set(config.get("roles", {}).keys())

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
            role = _find_role(target_id, config, dynamic) or "guest"
            rate_info = _rate_state.get(target_id, {})
            min_count = rate_info.get("minute", {}).get("count", 0)
            day_count = rate_info.get("day", {}).get("count", 0)
            reply = (
                f"chat_id: {target_id}\n"
                f"role: {role}\n"
                f"messages this minute: {min_count}\n"
                f"messages today: {day_count}"
            )
    else:
        return None

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
            role = _find_role(chat_id, config, dynamic) or "guest"
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

    # ── TODO: owner role ───────────────────────────────────────────────────
    # When owner bypass is implemented:
    #   if role == "owner":
    #       admin_result = _handle_admin_command(context, config, dynamic)
    #       if admin_result is not None:
    #           return admin_result
    #       _record_message(chat_id)
    #       return {"allow": True}
    #
    # For now, owner_chat_id is not set in default config — the owner
    # interacts via CLI on the server, not via Telegram.
    # ──────────────────────────────────────────────────────────────────────

    # ── Unlisted user ──────────────────────────────────────────────────────
    if role is None:
        if config.get("deny_unlisted", False):
            reason = messages.get("unlisted_denied", "You don't have access to this agent.")
            return {"allow": False, "reason": reason}
        # All unlisted users fall into guest — the only active role.
        role = "guest"

    # ── Guest role — rate limit check ─────────────────────────────────────
    role_cfg = config.get("roles", {}).get(role, {})
    rate_limits = role_cfg.get("rate_limit", {})
    if rate_limits:
        limit_key = _check_rate_limit(chat_id, rate_limits)
        if limit_key:
            reason = messages.get(limit_key, "Rate limit exceeded. Please try again later.")
            alerts = config.get("alerts", {})
            if alerts.get("on_rate_limit", False):
                _notify_owner(config, limit_key, chat_id, f"role={role}")
            return {"allow": False, "reason": reason}

    # ── Action permission check ───────────────────────────────────────────
    action = _infer_action(context)
    if not _is_action_allowed(action, role_cfg):
        reason = messages.get("action_denied", "You don't have permission for that.")
        alerts = config.get("alerts", {})
        if alerts.get("on_action_denied", True):
            user_msg = context.get("message", "")[:80]
            _notify_owner(config, "action_denied", chat_id,
                          f"role={role} action={action} msg=\"{user_msg}\"")
        return {"allow": False, "reason": reason}

    # ── All checks passed ─────────────────────────────────────────────────
    _record_message(chat_id)
    return {"allow": True}
