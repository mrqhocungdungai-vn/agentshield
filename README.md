# AgentShield

Role-based access control middleware for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — deployed as a gateway hook, not a standalone bot.

AgentShield intercepts every incoming Telegram/Discord/Slack message **before** it reaches the agent. It enforces per-role allow/deny lists, rate limits, and action guards — transparently, with zero changes to the agent itself.

```
User sends message
      ↓
Hermes Gateway
      ↓
AgentShield hook (before_message)
  → Check role
  → Check rate limit
  → Check action permission
      ↓ allow          ↓ deny
Agent processes    User gets denial message
```

## Features

- **RBAC** — per-role allow/deny patterns with wildcards (`skill:*`, `command:*`)
- **Rate limiting** — per-minute and per-day limits per role
- **Action inference** — distinguishes `chat`, `command:x`, `skill:x`, `system:reset`, `system:stop`
- **Persistent role assignments** — `/as_assign` at runtime, survives restarts
- **Conversation logging** — every turn logged to `~/.hermes/logs/conversations/<chat_id>.jsonl`
- **Admin commands** — manage roles from Telegram without touching config files
- **Owner bypass** — your `owner_chat_id` always passes all checks

## Installation

```bash
git clone https://github.com/mrqhocungdungai-vn/agentshield
cd agentshield
bash install.sh
```

Then edit `~/.hermes/agentshield.yaml` and set your `owner_chat_id`, then restart the gateway:

```bash
hermes gateway restart
```

## Configuration

```yaml
agentshield:
  enabled: true
  owner_chat_id: "YOUR_TELEGRAM_CHAT_ID"  # get from @userinfobot
  deny_unlisted: false  # true = whitelist mode

  roles:
    admin:
      chat_ids: ["111111111"]
      allow: ["*"]
      rate_limit:
        messages_per_minute: 60
        messages_per_day: 2000

    user:
      chat_ids: ["222222222"]
      allow: ["chat", "skill:*", "command:help", "command:reset"]
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
    conversations: true  # logs to ~/.hermes/logs/conversations/<chat_id>.jsonl

  messages:
    rate_limit_minute: "⏳ Too fast. Please wait a minute."
    rate_limit_day: "📵 Daily limit reached. Try again tomorrow."
    action_denied: "🚫 You don't have permission for that."
    unlisted_denied: "❌ You don't have access to this agent."
```

## Admin Commands

Send these from your owner Telegram account (the `owner_chat_id`):

| Command | Description |
|---------|-------------|
| `/as_assign <chat_id> <role>` | Assign a role dynamically (persisted to disk) |
| `/as_revoke <chat_id>` | Remove a dynamic role assignment |
| `/as_roles` | List all dynamic assignments |
| `/as_info <chat_id>` | Show role and rate-limit state for a user |

Dynamic assignments take priority over static `chat_ids` in config. They survive gateway restarts (stored in `~/.hermes/agentshield_roles.json`).

## Action Types

AgentShield infers the action type from each message:

| Action | Triggers when |
|--------|--------------|
| `chat` | Regular text message |
| `command:<name>` | Slash command (e.g. `/model` → `command:model`) |
| `skill:<name>` | Skill invocation (e.g. `/skill run summarize`) |
| `system:reset` | `/reset`, `/new`, `/clear` |
| `system:stop` | `/stop`, `/cancel` |

Use wildcards in allow/deny lists: `skill:*` allows all skills, `command:*` allows all commands.

## How It Works

AgentShield is a Hermes **gateway hook** — a Python file that Hermes loads automatically from `~/.hermes/hooks/agentshield/`. It subscribes to two events:

- `before_message` — RBAC + rate limiting on every incoming message
- `agent:end` — conversation logging after every completed turn

No fork of Hermes required. No separate process. Just a hook.

## Running Tests

```bash
pip install pytest pytest-asyncio pyyaml
pytest tests/ -v
```

## License

MIT
