# AgentShield 🛡️

> **Multi-tenant AI Agent Gateway & Marketplace Infrastructure**
> Open-source. Community-driven. Built for the world.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-Join%20us-5865F2)](https://discord.gg/agentshield)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-orange.svg)]()

---

**The missing infrastructure layer for AI agents.**

Today, if you build an AI agent (Hermes, OpenClaw, Claude Code, or any LLM agent) and want to sell access to it — you hit a wall. Your users get the same permissions as you. There's no access control, no user isolation, no billing, no CRM. You either build all of that yourself or you don't ship.

AgentShield solves this. It's a gateway + platform that sits between your AI agent and your users, giving you:

- 🔒 **Permission control** — users can only do what you allow
- 🐳 **Per-user Docker sandboxes** — full isolation, clone of your agent, user can't touch the original
- 💰 **Automatic billing** — usage-based or subscription, no manual bank transfers
- 📊 **Built-in CRM** — powered by Twenty (open-source Salesforce alternative)
- 🌐 **Marketplace-ready** — publish your agent, earn from day one

---

## The Problem

You've built a powerful AI agent. Now you want to:

1. Let a customer use it as a customer service employee
2. Sell access to it on a marketplace like [openknowledgemarket.com](https://openknowledgemarket.com)
3. Give each user their own isolated environment
4. Get paid automatically without manually confirming bank transfers

But when you expose your Hermes/OpenClaw agent via Telegram or any gateway — **public users get owner-level permissions.** They can read your memory, modify your skills, break your agent.

There's no solution for this today. AgentShield is that solution.

---

## Roadmap

### Phase 1 — Gateway Proxy (in progress) 🚧
*Goal: Ship something useful in days, not months.*

- Role-based access control (owner vs. public user)
- Telegram gateway with user permission tiers
- Per-user rate limiting and command filtering
- Simple config file to define what users can/cannot do
- Works with any Hermes agent out of the box

### Phase 2 — Docker Sandbox Isolation
*Goal: True multi-tenant isolation.*

- Per-user Docker container spun up on first access
- Full clone of the agent — user gets all features, owner is untouched
- Container lifecycle management (start, stop, destroy)
- Persistent user state within their sandbox
- Resource limits per container

### Phase 3 — CRM Integration (Twenty)
*Goal: Know your users, manage relationships.*

- [Twenty CRM](https://github.com/twentyhq/twenty) integration
- Auto-create contact record on first user interaction
- Log conversation summaries to CRM
- Deal pipeline for user upgrades
- Activity timeline per user

### Phase 4 — Automated Billing
*Goal: Get paid without lifting a finger.*

- Stripe / payment gateway integration
- Usage-based billing (per message, per task)
- Subscription tiers
- Auto-suspend on non-payment
- Invoice generation

### Phase 5 — Marketplace SDK
*Goal: Publish once, earn forever.*

- Package your agent as a deployable unit
- One-click publish to marketplaces
- Revenue sharing infrastructure
- Agent versioning and updates

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        AgentShield                          │
│                                                             │
│  User (Telegram/API)                                        │
│         │                                                   │
│         ▼                                                   │
│  ┌─────────────┐     ┌──────────────┐     ┌─────────────┐  │
│  │   Gateway   │────▶│ Auth & Roles │────▶│  Rate Limit │  │
│  │   Proxy     │     │   Engine     │     │   & Filter  │  │
│  └─────────────┘     └──────────────┘     └──────┬──────┘  │
│                                                  │          │
│                      ┌───────────────────────────┤          │
│                      │                           │          │
│              Phase 1 ▼               Phase 2 ▼   │          │
│         ┌────────────────┐    ┌────────────────┐ │          │
│         │  Owner Agent   │    │  User Sandbox  │ │          │
│         │  (Protected)   │    │  (Docker clone)│ │          │
│         └────────────────┘    └────────────────┘ │          │
│                                                  │          │
│         ┌──────────────┐      ┌────────────────┐ │          │
│         │  Twenty CRM  │      │    Billing     │ │          │
│         │  (Phase 3)   │      │   (Phase 4)    │ │          │
│         └──────────────┘      └────────────────┘ │          │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start (Phase 1)

```bash
# Clone the repo
git clone https://github.com/mrqhocungdungai-vn/agentshield.git
cd agentshield

# Configure
cp config/example.yaml config/config.yaml
# Edit config.yaml — set your Telegram bot token, agent path, user roles

# Run
docker compose up -d
# or: python3 gateway/main.py
```

---

## Contributing

AgentShield is community-built. We need:

- 🐍 Python developers (gateway proxy, Docker orchestration)
- 🐳 DevOps engineers (container management, k8s)
- 💳 Payment integration (Stripe, crypto)
- 📊 CRM integration (Twenty)
- 🌍 Translators and documentation writers

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get started.

---

## Why Open Source?

The infrastructure for selling AI agent access should be a public good — not locked inside a SaaS. If you build an agent, you should own the full stack. AgentShield gives you that stack, for free, forever.

---

## License

MIT. Build whatever you want with it.

---

*Built with ❤️ by the community. Inspired by real problems from real builders.*
