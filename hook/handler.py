"""
AgentShield — Hermes before_message hook (v1.0.0)
==================================================
Security middleware for customer-facing Hermes agents.
Philosophy: ONE role. Maximum security. Every user is a guest.

Flow:
  User message
      → Load config
      → Check rate limit  →  exceeded  →  reply + stop
      → Check allow/deny  →  denied    →  reply + stop
      → Pass to agent
      → Log conversation turn (agent:end)

Config: ~/.hermes/agentshield.yaml
"""

from __future__ import annotations

import fnmatch, json, os, threading, time, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB soft cap
_RATE_TTL = 86400 * 2              # Evict entries not seen for 2 days


# ── Paths ────────────────────────────────────────────────────────────────────

def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


# ── Config ───────────────────────────────────────────────────────────────────

def _load_config() -> Dict[str, Any]:
    for path in [_home() / "agentshield.yaml", Path(__file__).parent / "config.yaml"]:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return data.get("agentshield", data)
            except Exception as e:
                print(f"[agentshield] Config load error {path}: {e}", flush=True)
    return {}


# ── Owner alert ──────────────────────────────────────────────────────────────

def _notify_owner(config: Dict[str, Any], event: str, chat_id: str, detail: str) -> None:
    """Send alert to owner via Telegram Bot API. Token from env var only — never config."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    owner_id = str(config.get("owner_chat_id", ""))
    if not token or not owner_id:
        return
    emoji = {"action_denied": "🚫", "rate_limit_minute": "⏳", "rate_limit_day": "📵"}.get(event, "⚠️")
    text = f"{emoji} <b>AgentShield Alert</b>\nEvent: <code>{event}</code>\nUser: <code>{chat_id}</code>\n{detail}"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"  # nosec B310
        payload = json.dumps({"chat_id": owner_id, "text": text, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(  # nosec B310
            urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}),
            timeout=5,
        )
    except Exception as e:
        print(f"[agentshield] Alert failed: {e}", flush=True)


# ── Rate limiter — thread-safe with TTL eviction ─────────────────────────────

_rate_state: Dict[str, Dict[str, Any]] = {}
_rate_lock = threading.Lock()
_last_evict: float = 0.0


def _evict_stale(now: float) -> None:
    global _last_evict
    if now - _last_evict < 3600:
        return
    _last_evict = now
    stale = [k for k, v in _rate_state.items() if now - v.get("_seen", 0) > _RATE_TTL]
    for k in stale:
        del _rate_state[k]
    if stale:
        print(f"[agentshield] Evicted {len(stale)} stale rate entries", flush=True)


def _check_rate(chat_id: str, limits: Dict[str, int]) -> Optional[str]:
    """Returns None if OK, or a message key if exceeded."""
    now = time.time()
    with _rate_lock:
        _evict_stale(now)
        s = _rate_state.setdefault(chat_id, {"_seen": now})
        s["_seen"] = now
        if (n := limits.get("messages_per_minute")):
            b = s.setdefault("min", {"ts": now, "count": 0})
            if now - b["ts"] > 60:
                b.update({"ts": now, "count": 0})
            if b["count"] >= n:
                return "rate_limit_minute"
        if (n := limits.get("messages_per_day")):
            b = s.setdefault("day", {"ts": now, "count": 0})
            if now - b["ts"] > 86400:
                b.update({"ts": now, "count": 0})
            if b["count"] >= n:
                return "rate_limit_day"
    return None


def _record(chat_id: str) -> None:
    """Increment counters after a message passes all checks."""
    with _rate_lock:
        s = _rate_state.get(chat_id, {})
        s["_seen"] = time.time()
        for name in ("min", "day"):
            if (b := s.get(name)):
                b["count"] += 1


# ── Action inference ─────────────────────────────────────────────────────────

def _infer_action(ctx: Dict[str, Any]) -> str:
    if not ctx.get("is_command"):
        return "chat"
    cmd = (ctx.get("command") or "").lower().strip()
    if cmd in {"reset", "new", "clear"}:
        return "system:reset"
    if cmd in {"stop", "cancel"}:
        return "system:stop"
    if cmd == "skill":
        parts = ctx.get("message", "").strip().lstrip("/").split()
        return f"skill:{parts[2] if len(parts) > 2 else '*'}"
    return f"command:{cmd}"


# ── Permission check ─────────────────────────────────────────────────────────

def _allowed(action: str, cfg: Dict[str, Any]) -> bool:
    """Deny-overrides-allow. Empty allow list = no restrictions."""
    allow: List[str] = cfg.get("allow", [])
    deny: List[str] = cfg.get("deny", [])
    if any(fnmatch.fnmatch(action, p) for p in deny):
        return False
    if any(fnmatch.fnmatch(action, p) for p in allow):
        return True
    return len(allow) == 0


# ── Conversation logging ─────────────────────────────────────────────────────

def _log(config: Dict[str, Any], chat_id: str, user_msg: str, reply: str) -> None:
    if not config.get("logging", {}).get("conversations", True):
        return
    try:
        log_dir = _home() / "logs" / "conversations"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{chat_id}.jsonl"
        if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            tmp = log_path.with_suffix(".tmp")
            tmp.write_text("".join(lines[max(1, len(lines) // 5):]), encoding="utf-8")
            tmp.replace(log_path)
        entry = {"ts": datetime.utcnow().isoformat(), "chat_id": chat_id, "user": user_msg, "agent": reply}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[agentshield] Log error: {e}", flush=True)


# ── Main handler ─────────────────────────────────────────────────────────────

async def handle(event_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Hook entry point. Never raises — fail-open to avoid dropping customer messages."""
    try:
        return await _inner(event_type, context)
    except Exception as e:
        print(f"[agentshield] Unexpected error ({event_type}): {e}", flush=True)
        return {"allow": True}


async def _inner(event_type: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    config = _load_config()

    # agent:end — log conversation and exit
    if event_type == "agent:end":
        if config and config.get("enabled", True):
            chat_id = str(ctx.get("user_id") or ctx.get("chat_id") or "")
            _log(config, chat_id, ctx.get("message", ""), ctx.get("response", ""))
        return {"allow": True}

    # Disabled or missing config — pass through
    if not config or not config.get("enabled", True):
        return {"allow": True}

    chat_id = str(ctx.get("chat_id") or ctx.get("user_id") or "")
    if not chat_id:
        return {"allow": True}

    msgs = config.get("messages", {})

    # Rate limit check (applied equally to all users)
    rate_limits = config.get("rate_limit", {})
    if rate_limits:
        key = _check_rate(chat_id, rate_limits)
        if key:
            _notify_owner(config, key, chat_id, "rate limit hit")
            return {"allow": False, "reason": msgs.get(key, "Rate limit exceeded. Please try again later.")}

    # Action permission check
    action = _infer_action(ctx)
    if not _allowed(action, config):
        _notify_owner(config, "action_denied", chat_id, f"action={action}")
        return {"allow": False, "reason": msgs.get("action_denied", "That feature isn't available in this chat.")}

    _record(chat_id)
    return {"allow": True}
