# AgentShield Roadmap

## Phase 1 — Gateway Proxy ⚡ (Current Focus)

**Goal:** Working access control in days. Deployable by any Hermes agent owner.

### Core Features
- [ ] Telegram bot gateway layer
- [ ] Role system: `owner`, `admin`, `user`, `guest`
- [ ] Command allowlist/denylist per role
- [ ] Per-user rate limiting
- [ ] Config file (YAML) for defining roles and permissions
- [ ] Logging of all user interactions
- [ ] Simple web dashboard (optional, stretch goal)

### Success Criteria
- A Hermes customer-service agent can be deployed on Telegram
- Public users can only use approved commands
- Owner retains full control
- Zero code changes needed to the underlying agent

---

## Phase 2 — Docker Sandbox Isolation 🐳

**Goal:** True per-user isolation. Each user gets a full clone of the agent.

### Core Features
- [ ] Docker Compose orchestration for agent containers
- [ ] Per-user container lifecycle (create on first login, destroy on cancel)
- [ ] Volume management for user state persistence
- [ ] Resource limits (CPU, RAM, disk per container)
- [ ] Container health monitoring
- [ ] Auto-cleanup of idle containers

### Success Criteria
- User can delete files inside their container — owner agent untouched
- 100 concurrent users, each in their own sandbox
- Container boot time < 10 seconds

---

## Phase 3 — CRM Integration (Twenty) 📊

**Goal:** Know your users. Build relationships. Manage your pipeline.

### Core Features
- [ ] Twenty CRM deployment (Docker)
- [ ] Auto-create contact on first user message
- [ ] Log conversation summaries to Twenty
- [ ] User tier tracking (free, paid, enterprise)
- [ ] Deal pipeline for upgrades
- [ ] Webhook from gateway → Twenty

---

## Phase 4 — Automated Billing 💳

**Goal:** Revenue on autopilot.

### Core Features
- [ ] Stripe integration
- [ ] Usage-based billing (per message / per task)
- [ ] Subscription tiers
- [ ] Auto-suspend container on payment failure
- [ ] Invoice PDF generation
- [ ] Crypto payment option (USDT/ETH)

---

## Phase 5 — Marketplace SDK 🌐

**Goal:** Package once, sell everywhere.

### Core Features
- [ ] Agent packaging format (manifest.yaml)
- [ ] One-click publish to openknowledgemarket.com
- [ ] Version management
- [ ] Revenue sharing smart contract
- [ ] Agent discovery API

---

## Beyond

- Multi-agent orchestration (owner delegates subtasks to specialized agents)
- Agent-to-agent communication protocol
- Federated agent marketplace (no central authority)
- Mobile app for managing your agent fleet
