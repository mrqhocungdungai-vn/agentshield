# AgentShield

**Role-based access control middleware for [Hermes Agent](https://github.com/NousResearch/hermes-agent)**

AgentShield turns Hermes into a customer-facing AI employee — available 24/7, safe, and rate-limited — without forking or modifying Hermes source code.

```
Customer sends message (Telegram/Discord/...)
          ↓
Hermes Gateway
          ↓
AgentShield hook (before_message)
   → Resolve role
   → Check rate limit
   → Check action permission
          ↓ allow                  ↓ deny
Agent processes normally     Customer gets a polite message
          ↓
AgentShield hook (agent:end)
   → Log conversation turn
```

---

## Design Philosophy

AgentShield operates on a simple principle: the agent serves customers, not the other way around. Customers get a helpful, rate-limited chat interface. The owner gets full control. The system protects itself by default — nothing dangerous is ever exposed to the public layer.

---

## Features

- **Auto-guest** — all external users automatically get the guest role. No whitelist needed.
- **Rate limiting** — per-minute and per-day limits per role
- **Action control** — allow/deny by action type (`chat`, `command:*`, `skill:*`, `system:*`)
- **Action inference** — distinguishes `chat`, `command:x`, `skill:x`, `system:reset`, `system:stop`
- **Persistent role assignments** — assign roles at runtime via `/as_assign`, survives gateway restarts
- **Conversation logging** — every turn logged to `~/.hermes/logs/conversations/<chat_id>.jsonl`
- **Owner alerts** — Telegram notification when suspicious actions are blocked
- **Zero-fork** — a single hook file, no changes to Hermes required

---

## Deployment Architecture

AgentShield is designed for the **customer-facing agent** model:

```
Owner
  → Interacts with agent via CLI directly on the server
  → Full tools, no restrictions (owner role planned — see Roadmap)

Customers
  → Interact via Telegram / messaging platform
  → Chat only, rate-limited, no dangerous tools exposed
```

Hermes config uses `platform_toolsets.telegram: [safe]` to completely remove
`terminal`, `file`, and `process` tool schemas from the agent's context.
AgentShield blocks at the **message layer**, Hermes config blocks at the **tool layer**.
Two independent layers of defense.

---

## Installation

### Requirements
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed and running
- Python 3.9+
- PyYAML (`pip install pyyaml`)

### Step 1 — Clone the repo

```bash
git clone https://github.com/mrqhocungdungai-vn/agentshield
cd agentshield
```

### Step 2 — Run the install script

```bash
bash install.sh
```

This will:
- Copy `hook/handler.py` and `hook/HOOK.yaml` into `~/.hermes/hooks/agentshield/`
- Create a default config at `~/.hermes/agentshield.yaml` (if not already present)

### Step 3 — Configure AgentShield

Edit `~/.hermes/agentshield.yaml`:

```yaml
agentshield:
  enabled: true

  roles:
    guest:
      allow: ["chat"]
      deny: ["command:*", "system:*", "terminal", "skill:*"]
      rate_limit:
        messages_per_minute: 10
        messages_per_day: 200

  messages:
    rate_limit_minute: "I'm handling a lot of messages right now — please try again in a moment 😊"
    rate_limit_day: "You've reached today's message limit. Feel free to continue tomorrow!"
    action_denied: "That feature isn't available in this chat. Please contact our support team 😊"
```

### Step 4 — Configure Hermes

In `~/.hermes/config.yaml`, switch the Telegram toolset to `safe` to remove dangerous tools:

```yaml
platform_toolsets:
  telegram:
    - safe    # web + vision only — no terminal/file/process
```

Allow all Telegram users through Hermes (AgentShield handles access control):

```bash
# Add to ~/.hermes/.env
TELEGRAM_ALLOW_ALL_USERS=true
```

### Step 5 — Restart the gateway

```bash
hermes gateway restart
```

Verify the hook loaded:

```bash
journalctl --user -u hermes-gateway -n 20 | grep agentshield
# Expected output:
# [hooks] Loaded hook 'agentshield' for events: ['before_message', 'agent:end']
```

---

## Full Configuration Reference

See [`config/agentshield.yaml.example`](config/agentshield.yaml.example) for a full annotated example.

### Role system

| Role | Status | Description |
|------|--------|-------------|
| `owner` | Planned | Bypasses all checks, can use `/as_*` admin commands. Set via `owner_chat_id` in config. |
| `guest` | Active | Default for all users. Chat only, rate-limited. No dangerous actions allowed. |

All external users automatically fall into `guest`. No whitelist configuration needed.

### Action types

| Action | Triggered when |
|--------|---------------|
| `chat` | Regular text message |
| `command:<name>` | Slash command (e.g. `/help` → `command:help`) |
| `skill:<name>` | Skill invocation (e.g. `/skill run summarize`) |
| `system:reset` | `/reset`, `/new`, `/clear` |
| `system:stop` | `/stop`, `/cancel` |

---

## Management

All management is done **directly on the server via CLI**:

```bash
# SSH into the server
ssh user@your-server

# Edit roles, rate limits, messages
nano ~/.hermes/agentshield.yaml

# View conversation logs
ls ~/.hermes/logs/conversations/
cat ~/.hermes/logs/conversations/<chat_id>.jsonl

# Restart gateway to apply config changes
hermes gateway restart

# View dynamic role assignments
cat ~/.hermes/agentshield_roles.json
```

---

## Running Tests

```bash
pip install pytest pytest-asyncio pyyaml
pytest tests/ -v
```

---

## Project Goal

> Turn Hermes Agent into a real online customer care employee — available 24/7 to handle customer inquiries — while keeping the underlying system completely self-protected.

AgentShield is the armor that lets the agent work in the real world without exposing the owner's infrastructure.

---

## Contact & Follow

- **TikTok:** [@mr.q.hoc.ung.dung.ai](https://www.tiktok.com/@mr.q.hoc.ung.dung.ai)
- **GitHub:** [mrqhocungdungai-vn/agentshield](https://github.com/mrqhocungdungai-vn/agentshield)

---

## Contributing

Pull requests and issues are welcome.

---

> ⚠️ **A note from the author**
>
> This project was built by **Hermes Agent itself**, guided by an ICT engineer who is not a professional developer.
> The goal is practical and learning-oriented — not production-perfect.
>
> There are likely gaps in security hardening, edge case handling, and code quality.
> If you are a developer and see something worth improving, **issues and PRs are very welcome**. 
>
> Let's build something that lets AI agents do real work — safely, reliably, and profitably.

---

## License

MIT
