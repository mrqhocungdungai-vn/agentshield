# AgentShield Roadmap

AgentShield has one job: be a reliable, minimal security hook for customer-facing Hermes agents.

This roadmap reflects that focus. Features outside this scope are explicitly listed at the bottom.

---

## Phase 1 — Stable Gateway Hook (current)

**Goal:** Rock-solid rate limiting, action blocking, and conversation logging for the guest role. Clear install process. Well-tested. Zero footprint on Hermes internals.

### Features
- [x] Rate limiting per user (messages per minute + messages per day)
- [x] Action inference and allow/deny by action type
- [x] Auto-guest — all external users are guest by default, no whitelist required
- [x] Prompt injection guard (case-insensitive pattern matching)
- [x] Human escalation detection with owner alert
- [x] Conversation logging to `~/.hermes/logs/conversations/<chat_id>.jsonl` with soft rotation
- [x] Owner Telegram alerts on blocked actions
- [x] Thread-safe rate limiter with TTL eviction
- [x] Atomic config and role file writes
- [x] Zero-fork install via single hook file

### Success Criteria
- Any Hermes owner can deploy a customer-facing Telegram agent safely in under 30 minutes
- Single YAML config file, no code changes required
- Full test coverage for hook logic (target: >= 90%)
- No exception in the hook can crash the Hermes gateway

---

## Phase 2 — Hardening and Observability

**Goal:** Make the hook production-grade for real deployments handling sustained traffic.

### Features
- [ ] Structured JSON log format (replace print statements with structured output)
- [ ] Metrics output — blocked requests, rate limit hits, escalation count (stdout or file, no external dependency)
- [ ] Graceful config reload without gateway restart (detect config file changes via mtime)
- [ ] Improved owner alert formatting — include user message excerpt and action type in a consistent template
- [ ] Config validation on startup — surface YAML errors and missing fields before the first message arrives

### Success Criteria
- A blocked action produces a log line parseable by standard log aggregators (jq, grep, etc.)
- Config errors are reported clearly at startup, not silently at runtime
- Metrics output is human-readable from `tail -f` and machine-parseable

---

## Phase 3 — Packaging

**Goal:** Make AgentShield installable as a proper, versioned package compatible with the Hermes hook registry.

### Features
- [ ] pip-installable package (`pip install agentshield`)
- [ ] Hermes hook registry compatibility (standard manifest format)
- [ ] Versioned releases with changelog
- [ ] Install command: `agentshield install` copies hook files and creates default config

### Success Criteria
- Installation reduces to two commands: `pip install agentshield && agentshield install`
- Each release has a changelog entry with breaking changes clearly marked

---

## Out of Scope

Features like Docker sandbox isolation, CRM integration, billing, and marketplace infrastructure are intentionally out of scope for AgentShield. These belong to a separate infrastructure layer.

If you are interested in that direction, see [openknowledgemarket.com](https://openknowledgemarket.com).
