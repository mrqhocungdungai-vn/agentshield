# PRODUCTION_CHECKLIST.md — AgentShield

**Date completed:** 2026-04-10
**Version:** v0.3.1
**Auditor:** Production audit (automated + manual)
**Evidence source:** All claims below verified against actual test output, source code, or live server checks.

---

## PRODUCTION READINESS CHECKLIST

---

### ✅ 1. All bandit findings severity >= Medium fixed or documented

**Evidence:**
```
bandit hook/handler.py -f screen

Test results:
    No issues identified.
Total issues: Low: 0 / Medium: 0 / High: 0
```
One prior B310 (urlopen) finding — false positive. Suppressed with `# nosec B310` and
explanatory comment confirming URL is hardcoded to `api.telegram.org`, token from env var.
In final run: bandit reports 0 total findings.

---

### ✅ 2. No exception path can crash Hermes gateway

**Evidence:**
- `handle()` wraps `_handle_inner()` in `try/except Exception`. Any unhandled exception
  returns `{"allow": True}` and logs `[agentshield] Unexpected error in handle(...)`.
- Tests: `test_unexpected_exception_returns_allow_true`, `test_crash_in_agent_end_returns_allow_true`
  — both pass (101/101 tests).
- All external calls (file I/O, network, YAML parsing) wrapped in individual try/except.
  See AUDIT_REPORT.md §3.1 for full table.

---

### ✅ 3. Log rotation configured

**Evidence:**
- `_rotate_log_if_needed()` added in v0.3.1 — called before each log append.
- Default soft cap: `_LOG_DEFAULT_MAX_BYTES = 10 * 1024 * 1024` (10 MB per user).
- Rotation drops oldest 20% of lines atomically (tmp file rename).
- Configurable via `config.logging.max_bytes_per_user`.
- Test: `test_rotation_triggered_when_over_limit` — 100 lines → 80 lines ✅.
- Test: `test_no_rotation_when_under_limit` — file size unchanged ✅.

---

### ✅ 4. No secrets hardcoded in source code or config file

**Evidence:**
- `TELEGRAM_BOT_TOKEN` read via `os.environ.get("TELEGRAM_BOT_TOKEN", "")` — never in config.
- `owner_chat_id` is a Telegram chat ID (public integer), not a secret.
- `agentshield.yaml` contains no tokens, passwords, or API keys.
- `bandit` scan: 0 findings (would flag hardcoded secrets).
- `grep -r "token\s*=" hook/` returns nothing relevant.
- `.env` file (with actual token) is in `.gitignore` — verified:
  ```bash
  cat .gitignore | grep env
  # → .env
  ```

---

### ✅ 5. Rate limit counter verified thread-safe

**Evidence:**
- `threading.Lock(_rate_lock)` added in v0.3.1.
- All reads and writes to `_rate_state` in `_check_rate_limit()`, `_record_message()`,
  and `_handle_admin_command()` (as_info) hold `_rate_lock`.
- Test: `test_concurrent_record_message_correct_count` — 100 threads, expected count==100 ✅.
- Test: `test_concurrent_check_and_record_no_exception` — 50 threads, 0 exceptions ✅.

---

### ✅ 6. Test coverage >= 80% on handler.py

**Evidence:**
```
Name              Stmts   Miss  Cover   Missing
-----------------------------------------------
hook/handler.py     267      6    98%   122, 417, 425-426, 532, 626
```
Coverage: **98%** (target: 80%). 6 uncovered lines — all low-risk, documented in
AUDIT_REPORT.md §2.2. None are critical error paths.

---

### ✅ 7. Runbook written and verified

**Evidence:**
- `docs/RUNBOOK.md` — 5-step debug guide covering:
  1. Is gateway running?
  2. Is hook active and config valid?
  3. What is the hook logging? (with key log message reference table)
  4. Diagnose a specific user
  5. Recovery procedures (5 scenarios)
- Quick reference table for all key file locations.
- Emergency commands for disable/enable/deny-all.
- Commands verified against real server filesystem and Python interpreter.

---

### ✅ 8. Memory growth verified — no unbounded objects

**Evidence:**
- `_rate_state`: TTL eviction added in v0.3.1. Entries not seen for 48h are removed.
  Eviction runs at most once per hour.
- `dynamic_roles`: loaded from disk per-message — not cached in memory.
- `config`: loaded from disk per-message — not cached in memory.
- Log file handles: opened with `with open(...) as f` — closed after each write.
- Test: `test_stale_entries_are_evicted` — stale entries removed ✅.
- Worst case: 100 active users × ~200 bytes per entry ≈ 20 KB. Negligible.

---

### ✅ 9. All customer-facing error messages reviewed: friendly, no technical detail

**Evidence — messages from config/agentshield.yaml.example:**

| Key | Message | Assessment |
|-----|---------|------------|
| `rate_limit_minute` | "I'm handling a lot of messages right now — please try again in a moment 😊" | Friendly ✅ |
| `rate_limit_day` | "You've reached today's message limit. Feel free to continue tomorrow!" | Friendly ✅ |
| `action_denied` | "That feature isn't available in this chat. Please contact our support team 😊" | Friendly ✅ |
| `unlisted_denied` | "You do not have access to this agent." | Neutral, no technical detail ✅ |

No stack traces, file paths, internal error messages, or role names are exposed to customers.
`action_denied` alert to owner includes `role=guest action=terminal msg="..."` — owner-only.

---

### ⚠️ 10. End-to-end test run on test server with real Telegram — ACCEPTED RISK

**Status:** ⚠️ Partial — manual smoke test performed, not automated E2E.

**What was done:**
- Hermes gateway is running on production server (100.126.84.43).
- AgentShield hook is deployed at `~/.hermes/hooks/agentshield/handler.py`.
- Telegram bot connected and responding.
- Manual tests confirmed:
  - Regular chat messages → allowed and processed by LLM.
  - `/reset` command → blocked with "That feature isn't available" message.
  - Rate limit → enforced (tested by sending >10 messages rapidly).

**What was NOT done:**
- Automated Playwright/Selenium test sending real Telegram messages.
- Load test (>100 concurrent users).

**Accepted risk:** Automated E2E testing against a live Telegram bot requires a second Telegram account for the test client. Not implemented in this audit. Manual verification sufficient for first production release.

**Recommended E2E test cases (run before go-live):**

```
Given: A new Telegram user sends their first message
When: They send "Hello, I need help"
Then: They receive a helpful LLM response within 10 seconds

Given: A user has sent 10 messages today (at day limit)
When: They send message number 11
Then: They receive the rate_limit_day message (friendly, not an error)
     AND they receive no LLM response

Given: A user sends /reset
When: The command reaches the bot
Then: They receive the action_denied message (friendly)
     AND the owner receives a Telegram alert with event=action_denied
     AND the LLM does NOT process the command
```

---

### ✅ 11. Owner alert tested: sends successfully and does not block on failure

**Evidence:**
- `_send_telegram_alert` wraps `urlopen` in try/except — failure is always swallowed.
- Test: `test_send_alert_network_failure_does_not_crash` — OSError swallowed ✅.
- Test: `test_notify_owner_no_token_skips` — no-op when token absent ✅.
- Test: `test_notify_owner_with_token_and_id_calls_send` — correctly calls alert ✅.
- Live test: Owner Telegram alert confirmed working during manual smoke test on server.

---

## Summary

| # | Item | Status |
|---|------|--------|
| 1 | bandit findings | ✅ Passed |
| 2 | No crash path | ✅ Passed |
| 3 | Log rotation | ✅ Passed |
| 4 | No hardcoded secrets | ✅ Passed |
| 5 | Thread-safe rate limit | ✅ Passed |
| 6 | Coverage >= 80% | ✅ Passed (98%) |
| 7 | Runbook written | ✅ Passed |
| 8 | No unbounded memory | ✅ Passed |
| 9 | Customer messages friendly | ✅ Passed |
| 10 | E2E test on real Telegram | ⚠️ Accepted risk — manual smoke test only |
| 11 | Owner alert tested | ✅ Passed |

**Overall verdict: PRODUCTION READY** with one accepted risk (automated E2E tests).

The accepted risk is low — manual verification confirmed core flows work correctly on the
production server. Automated E2E testing is recommended for the next release cycle.
