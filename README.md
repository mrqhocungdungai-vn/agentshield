# AgentShield 🛡

Security middleware for customer-facing Hermes Agents

Built for AI agents that face the internet directly: sales bots, customer service agents, support assistants.

---

## Philosophy: One role. Maximum security.

AgentShield has exactly **ONE role**: every user is a guest.

- No role hierarchy
- No admin commands over chat
- No way to escalate privileges through the messaging interface
- The only way to change configuration is through the TUI on the server

---

## How it works

```
User sends message
        │
        ▼
Load config (~/.hermes/agentshield.yaml)
        │
        ▼
Check rate limit ──── exceeded ──→ Reply with rate_limit message, stop
        │
        ▼ (ok)
Check allow/deny ─── denied ──→ Reply with action_denied message, stop
        │
        ▼ (allowed)
Pass to Hermes agent
        │
        ▼
Log conversation turn (agent:end)
```

---

## Features

- **Single universal role** — zero privilege escalation surface
- **Rate limiting** — per-minute and per-day, applied equally to all users
- **Action filtering** — allow/deny by action type (chat / command / skill / system)
- **Conversation logging** — `.jsonl` per chat_id, with soft size cap
- **Owner alert** — Telegram notification on blocked actions
- **TUI configuration** — no manual YAML editing, no remote config interface
- **Zero-fork** — single hook file, no changes to Hermes

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    INTERNET                          │
│   Telegram / WhatsApp / Any platform                 │
└─────────────────────┬────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────┐
│              HERMES GATEWAY                          │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │  LAYER 1: AgentShield (this hook)           │     │
│  │  • Rate limit check                         │     │
│  │  • Action allow/deny check                  │     │
│  │  • Conversation logging                     │     │
│  └──────────────────┬──────────────────────────┘     │
│                     │ allowed                        │
│  ┌──────────────────▼──────────────────────────┐     │
│  │  LAYER 2: Hermes Agent                      │     │
│  │  • LLM reasoning                            │     │
│  │  • Tool execution                           │     │
│  │  • Response generation                      │     │
│  └─────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────┘

Config is ONLY editable via TUI on the server (SSH session).
Zero remote configuration surface.
```

---

## Installation

```bash
git clone https://github.com/mrqhocungdungai-vn/agentshield.git
cd agentshield
bash install.sh
```

The installer will:
1. Copy `hook/handler.py` and `HOOK.yaml` to `~/.hermes/hooks/agentshield/`
2. Copy the example config to `~/.hermes/agentshield.yaml` (if not already present)
3. Install `textual` if not available
4. Install the `agentshield-config` CLI command

Then restart the Hermes gateway:

```bash
hermes gateway restart
```

---

## Configuration via TUI

```bash
agentshield-config
```

The TUI has four screens:

- **Rate Limits** — set messages_per_minute and messages_per_day
- **Allow / Deny Rules** — manage action filters with preset buttons
- **Response Messages** — edit the text shown to users when blocked
- **Toggle enabled** — enable or disable AgentShield entirely

All changes are in-memory until **Save & Exit** is pressed.
Saves atomically to `~/.hermes/agentshield.yaml`.

```
┌─ AgentShield Configuration ─────────────────────────┐
│  One role. Maximum security.                        │
│                                                     │
│  [ Rate Limits              ]                       │
│  [ Allow / Deny Rules       ]                       │
│  [ Response Messages        ]                       │
│  [ Toggle AgentShield: ✅ Enabled ]                  │
│                                                     │
│  [ Save & Exit              ]                       │
│  [ Exit without saving      ]                       │
└─────────────────────────────────────────────────────┘
```

---

## What is intentionally NOT included

| Feature | Reason not included |
|---|---|
| Multiple roles | Role hierarchy = attack surface |
| Admin commands over Telegram | Chat = untrusted interface |
| Role assignment or promotion | Escalation path = security risk |
| Remote configuration interface | All config via server TUI only |
| Owner bypass via chat | No privileged users in the message path |

---

## Use cases

- **Telegram sales bot** — qualify leads, answer product questions
- **Customer service assistant** — handle support tickets, FAQs
- **Public-facing support agent** — triage requests before human handoff

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Optional | Bot token for owner alerts on blocked actions |
| `HERMES_HOME` | Optional | Override default `~/.hermes` path |

---

## File layout

```
agentshield/
├── hook/
│   ├── handler.py          # The hook — single file, <220 lines
│   └── HOOK.yaml           # Hook registration config
├── tui/
│   └── config_tui.py       # TUI launcher (agentshield-config)
├── config/
│   └── agentshield.yaml.example
├── install.sh
└── README.md
```

---

## License

MIT
