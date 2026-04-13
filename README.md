# AgentShield

**Minimal security middleware for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — built for customer-facing deployments.**

AgentShield is a single hook file that adds rate limiting, action blocking, and conversation logging to a Hermes gateway. It is designed for one specific model: an AI agent acting as a customer service or sales employee, exposed to the public via Telegram, while the owner retains full control via CLI over SSH.

```
Customer sends message (Telegram)
          ↓
Hermes Gateway
          ↓
AgentShield hook (before_message)
   → Check rate limit
   → Check action permission
   → Check prompt injection
   → Check escalation request
          ↓ allow                    ↓ deny
Agent processes normally       Customer gets a clear message
          ↓
AgentShield hook (agent:end)
   → Log conversation turn
```

---

## Do You Need AgentShield?

If your only concern is preventing dangerous tools from leaking to Telegram users, you may not need AgentShield at all. Hermes already supports platform-specific toolset restriction natively via `config.yaml`:

```yaml
platform_toolsets:
  telegram:
    - safe    # removes terminal, file, and process from agent context
```

Combined with `TELEGRAM_ALLOW_ALL_USERS=true` in your `.env`, this alone may be sufficient for many deployments.

**Install AgentShield only if you also need:**
- Per-user rate limiting (messages per minute and per day)
- Message-layer action blocking (block slash commands, skill invocations, system commands)
- Conversation logging per user
- Owner alerts when suspicious actions are blocked

---

## Prerequisites

- A server running Hermes Agent
- SSH access to that server (Tailscale recommended — gives you secure remote access without exposing open ports)
- Python 3.9+
- Basic comfort with YAML config files and a text editor over SSH

---

## Security Model

AgentShield operates as a second, independent layer on top of Hermes-native restrictions.

**Layer 1 — Hermes config (tool layer)**

Remove dangerous tools from the agent's context entirely when serving Telegram requests. This is Hermes-native and requires no extra code from AgentShield.

```yaml
# ~/.hermes/config.yaml
platform_toolsets:
  telegram:
    - safe    # terminal, file, process are never available in this context
```

**Layer 2 — AgentShield hook (message layer)**

Rate limiting and action blocking before the agent processes anything. AgentShield intercepts at the message level, not the tool level.

These two layers are independent. If AgentShield fails or is misconfigured, Hermes tool restrictions still apply. If Hermes config is misconfigured, AgentShield still rate-limits and blocks at the message layer. Defense in depth.

---

## Role Model

AgentShield uses a single role: **guest**.

Every external user is automatically a guest. There is no whitelist, no role assignment, no admin commands over Telegram.

Why single-role:
- The owner never interacts through Telegram — they SSH into the server directly.
- All public-facing users are untrusted by definition. There is no meaningful distinction between them.
- A single guest role eliminates entire categories of privilege escalation bugs.
- Less code means a smaller attack surface.

---

## Features

- **Auto-guest** — all external users automatically get the guest role. No whitelist needed.
- **Rate limiting** — per-minute and per-day message limits for the guest role.
- **Action control** — allow/deny by action type (`chat`, `command:*`, `skill:*`, `system:*`).
- **Action inference** — distinguishes `chat`, `command:x`, `skill:x`, `system:reset`, `system:stop`.
- **Prompt injection guard** — blocks messages matching known jailbreak patterns (case-insensitive).
- **Human escalation detection** — detects escalation keywords and alerts the owner.
- **Conversation logging** — every turn logged to `~/.hermes/logs/conversations/<chat_id>.jsonl` with soft rotation.
- **Owner alerts** — Telegram notification when suspicious actions are blocked.
- **Zero-fork** — a single hook file, no changes to Hermes source required.

---

## Installation

### Step 1 — Clone the repo

```bash
git clone https://github.com/mrqhocungdungai-vn/agentshield
cd agentshield
```

### Step 2 — Run the install script

```bash
bash install.sh
```

This copies `hook/handler.py` and `hook/HOOK.yaml` into `~/.hermes/hooks/agentshield/` and creates a default config at `~/.hermes/agentshield.yaml` if one does not already exist.

### Step 3 — Configure AgentShield

Edit `~/.hermes/agentshield.yaml`:

```yaml
agentshield:
  enabled: true

  roles:
    guest:
      allow:
        - "chat"
      deny:
        - "command:*"
        - "system:*"
        - "skill:*"
        - "terminal"
      rate_limit:
        messages_per_minute: 10
        messages_per_day: 200

  messages:
    rate_limit_minute: "I'm handling a lot of messages right now — please try again in a moment."
    rate_limit_day: "You've reached today's message limit. Feel free to continue tomorrow!"
    action_denied: "That feature isn't available in this chat. Please contact our support team."
```

See [`config/agentshield.yaml.example`](config/agentshield.yaml.example) for the full annotated reference including prompt injection guard and escalation detection options.

### Step 4 — Configure Hermes

In `~/.hermes/config.yaml`, restrict the Telegram toolset to `safe`:

```yaml
platform_toolsets:
  telegram:
    - safe    # web + vision only — terminal, file, and process are removed
```

In `~/.hermes/.env`, allow all Telegram users through Hermes (AgentShield handles access control):

```bash
TELEGRAM_ALLOW_ALL_USERS=true
```

### Step 5 — Restart the gateway

```bash
hermes gateway restart
```

Verify the hook loaded:

```bash
journalctl --user -u hermes-gateway -n 20 | grep agentshield
# Expected:
# [hooks] Loaded hook 'agentshield' for events: ['before_message', 'agent:end']
```

---

## Configuration Reference

### Action types

| Action | Triggered when |
|--------|----------------|
| `chat` | Regular text message |
| `command:<name>` | Slash command (e.g. `/help` → `command:help`) |
| `skill:<name>` | Skill invocation (e.g. `/skill run summarize` → `skill:summarize`) |
| `system:reset` | `/reset`, `/new`, `/clear` |
| `system:stop` | `/stop`, `/cancel` |

### Rate limiting

```yaml
rate_limit:
  messages_per_minute: 10   # max messages in a 60-second window
  messages_per_day: 200     # max messages in a 24-hour window
```

When a limit is hit, the customer receives the configured `messages.rate_limit_minute` or `messages.rate_limit_day` message. No error, no stack trace.

### Prompt injection guard

Blocks messages containing known jailbreak patterns using case-insensitive substring matching. Logs the user ID and a SHA-256 hash of the blocked message — never the message content itself.

```yaml
injection_guard:
  enabled: true
  patterns:
    - "ignore all previous instructions"
    - "you are now"
    - "act as"
    - "jailbreak"
    - "DAN mode"
  block_message: "Your message could not be processed."
```

### Human escalation detection

When a customer requests a human agent, AgentShield blocks the AI response, sends the configured escalation message to the customer, and notifies the owner via Telegram.

```yaml
escalation:
  enabled: true
  message: "Connecting you to a support agent — please hold on."
  keywords:
    - "speak to human"
    - "talk to human"
    - "human agent"
    - "/human"
```

### Owner alerts

Set `TELEGRAM_BOT_TOKEN` as an environment variable (never in config) and set `owner_chat_id` in `agentshield.yaml` to receive alerts when actions are blocked.

```yaml
alerts:
  on_action_denied: true
  on_rate_limit: false    # usually too noisy for production
```

---

## Administration

All administration is done over SSH. There are no Telegram admin commands and no web dashboard. This is intentional — the complexity budget is spent on reliability, not UI.

Tailscale is the recommended way to access your server. It avoids exposing SSH ports to the public internet and gives you stable hostname access without relying on IP addresses.

Minimum knowledge required: SSH, basic YAML editing, `hermes gateway restart`.

```bash
# SSH into the server
ssh user@your-server   # or: ssh user@your-tailscale-hostname

# Edit config
nano ~/.hermes/agentshield.yaml

# Apply changes
hermes gateway restart

# View conversation logs
ls ~/.hermes/logs/conversations/
cat ~/.hermes/logs/conversations/<chat_id>.jsonl

# Verify hook is active
journalctl --user -u hermes-gateway -n 50 | grep agentshield
```

---

## Running Tests

```bash
pip install pytest pytest-asyncio pyyaml
pytest tests/ -v
```

---

## Project Goal

Turn Hermes Agent into a real customer service employee — available 24/7, safe, and rate-limited — without forking or modifying Hermes source code. AgentShield is the armor that lets the agent work in the real world without exposing the owner's infrastructure.

---

## Contact

- **TikTok:** [@mr.q.hoc.ung.dung.ai](https://www.tiktok.com/@mr.q.hoc.ung.dung.ai)
- **GitHub:** [mrqhocungdungai-vn/agentshield](https://github.com/mrqhocungdungai-vn/agentshield)

---

> **A note from the author**
>
> This project was built by **Hermes Agent itself**, guided by an ICT engineer who is not a professional developer.
> The goal is practical and learning-oriented — not production-perfect.
>
> There are likely gaps in security hardening, edge case handling, and code quality.
> If you are a developer and see something worth improving, **issues and PRs are very welcome.**
>
> Let's build something that lets AI agents do real work — safely, reliably, and profitably.

---

## License

MIT
