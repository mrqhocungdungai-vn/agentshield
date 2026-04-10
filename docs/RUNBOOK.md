# RUNBOOK.md — AgentShield On-Call Debug Guide

**Audience:** Owner / operator responding to an incident at any hour.
**Scope:** AgentShield hook on server 100.126.84.43 (azureuser).

---

## Prerequisites — Gaining Access

```bash
ssh -i /tmp/agentshield_key.pem azureuser@100.126.84.43
```

All commands below run on the server as `azureuser`.

---

## Step 1 — Is the Gateway Running?

**Symptom:** Bot not responding to any message.

```bash
# Check if hermes gateway process is alive
ps aux | grep "hermes gateway" | grep -v grep

# If dead — restart it:
~/.hermes/hermes-agent/venv/bin/hermes gateway &
# Or if using a systemd unit:
sudo systemctl status hermes-gateway
sudo systemctl restart hermes-gateway
```

**Expected output when healthy:**
```
azureuser  12345  0.1  1.2  ... hermes gateway
```

**If process is dead and keeps dying:**
```bash
# Check last 50 lines of gateway output
journalctl -u hermes-gateway -n 50 --no-pager
# Or check screen/tmux session:
screen -ls
tmux ls
```

---

## Step 2 — Is AgentShield Hook Active?

**Symptom:** Gateway running but messages behave unexpectedly (all blocked, or all allowed with no rate limits).

```bash
# Check hook file exists and is valid Python
python3 -c "import sys; sys.path.insert(0,'~/.hermes/hooks/agentshield'); import handler; print('hook OK')"

# Check config file exists and is valid YAML
python3 -c "import yaml; d=yaml.safe_load(open('/home/azureuser/.hermes/agentshield.yaml')); print('config OK:', list(d.keys()))"

# Check hook enabled flag in config
grep -A3 "enabled" ~/.hermes/agentshield.yaml
```

**Expected:**
```
hook OK
config OK: ['agentshield']
enabled: true
```

**If config is malformed:**
```bash
# Validate YAML syntax
python3 -m yaml ~/.hermes/agentshield.yaml
# Fix manually then verify again
```

---

## Step 3 — What Is the Hook Logging?

**Symptom:** Need to understand what AgentShield is doing (blocking, allowing, errors).

```bash
# AgentShield logs go to gateway stdout. Check journalctl:
journalctl -u hermes-gateway -n 100 --no-pager | grep "\[agentshield\]"

# Or if running in a screen/tmux, check the output directly.
# Filter for specific events:
journalctl -u hermes-gateway --no-pager | grep "\[agentshield\]" | grep -E "denied|limit|error|failed|evict"

# Check conversation logs for a specific user
CHAT_ID="123456789"
cat ~/.hermes/logs/conversations/${CHAT_ID}.jsonl | tail -20 | python3 -m json.tool
```

**Key log messages to know:**

| Log line | Meaning |
|----------|---------|
| `[agentshield] Failed to load config ...` | Config YAML broken — fix immediately |
| `[agentshield] Failed to load role assignments` | roles.json corrupt — delete and recreate |
| `[agentshield] Failed to save role assignments` | Disk full or permissions issue |
| `[agentshield] Telegram alert failed: ...` | Owner alert broken — not blocking messages |
| `[agentshield] Conversation log failed: ...` | Log write error — disk full? |
| `[agentshield] Rotated log 123456.jsonl: ...` | Normal rotation, not an error |
| `[agentshield] Evicted N stale rate-limit entries` | Normal cleanup, not an error |
| `[agentshield] Unexpected error in handle(...)` | **BUG** — check the error and open an issue |

---

## Step 4 — Diagnose a Specific User

**Symptom:** A specific customer reports they can't send messages, or can't stop being rate-limited.

```bash
CHAT_ID="123456789"   # replace with actual chat_id

# 1. Check dynamic role assignment
cat ~/.hermes/agentshield_roles.json | python3 -m json.tool | grep "${CHAT_ID}"

# 2. Check conversation log (last 10 turns)
cat ~/.hermes/logs/conversations/${CHAT_ID}.jsonl | tail -10 | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    print(f\"{d['ts']} | role={d['role']} | user={d['user'][:60]!r}\")
"

# 3. Check rate state via /as_info admin command
# Send /as_info <chat_id> to the bot from your Telegram account
# (requires owner_chat_id to be configured — if not, run on server:)
python3 -c "
import sys; sys.path.insert(0,'~/.hermes/hooks/agentshield')
import handler as h
import json, time

# Simulate reading current state
h._load_config()  # won't be called but safe
cid = '${CHAT_ID}'
print('rate_state:', h._rate_state.get(cid, '(no entry — may have been reset)'))
print('dynamic roles:', h._load_dynamic_roles().get(cid, '(none — guest by default)'))
"

# 4. Reset rate limit for a user (emergency only)
# Edit the in-memory dict — requires sending a specially crafted admin command,
# OR restart the gateway (resets ALL counters):
sudo systemctl restart hermes-gateway
```

---

## Step 5 — Recovery Procedures

### 5a. Config file corrupted
```bash
# Restore from git
cd ~/agentshield
git checkout HEAD -- config/agentshield.yaml.example
cp config/agentshield.yaml.example ~/.hermes/agentshield.yaml
# Then edit to set correct values:
nano ~/.hermes/agentshield.yaml
```

### 5b. Role assignments file corrupted
```bash
# View current state
cat ~/.hermes/agentshield_roles.json

# If corrupt (not valid JSON):
rm ~/.hermes/agentshield_roles.json
# Roles reset to defaults (all users → guest). Re-assign manually via /as_assign.
```

### 5c. Disk full — logs
```bash
# Check disk usage
df -h ~/.hermes/

# Check which log files are largest
du -sh ~/.hermes/logs/conversations/*.jsonl 2>/dev/null | sort -rh | head -10

# Emergency: trim the largest log files
CHAT_ID="biggest_user"
wc -l ~/.hermes/logs/conversations/${CHAT_ID}.jsonl
# Keep last 1000 lines:
tail -1000 ~/.hermes/logs/conversations/${CHAT_ID}.jsonl > /tmp/trim.jsonl
mv /tmp/trim.jsonl ~/.hermes/logs/conversations/${CHAT_ID}.jsonl
```

### 5d. Gateway won't start — hook import error
```bash
# Test hook import in isolation
cd /home/azureuser/agentshield
source /home/azureuser/.hermes/hermes-agent/venv/bin/activate
python3 -c "
import sys
sys.path.insert(0, 'hook')
import handler
print('Import OK — version:', handler.__doc__.split('v')[1].split(')')[0] if 'v' in (handler.__doc__ or '') else 'unknown')
"

# If import fails — fix syntax error in handler.py, then verify:
python3 -m py_compile hook/handler.py && echo "Syntax OK"
```

### 5e. Owner alerts not arriving
```bash
# Check token is set
echo "TELEGRAM_BOT_TOKEN set: $([ -n \"$TELEGRAM_BOT_TOKEN\" ] && echo YES || echo NO)"
cat ~/.hermes/.env | grep TELEGRAM_BOT_TOKEN | sed 's/=.*/=***REDACTED***/'

# Test alert manually
python3 -c "
import os, sys
sys.path.insert(0, '/home/azureuser/agentshield/hook')
import handler as h
token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
if not token:
    print('ERROR: TELEGRAM_BOT_TOKEN not set in environment')
else:
    h._send_telegram_alert(token, 'YOUR_CHAT_ID', '🔧 AgentShield test alert')
    print('Alert sent (check Telegram)')
"
```

---

## Quick Reference — Key File Locations

| File | Purpose |
|------|---------|
| `~/.hermes/agentshield.yaml` | Main config |
| `~/.hermes/agentshield_roles.json` | Dynamic role assignments (persistent) |
| `~/.hermes/logs/conversations/<chat_id>.jsonl` | Per-user conversation log |
| `~/.hermes/.env` | API keys and tokens |
| `/home/azureuser/agentshield/hook/handler.py` | Hook source code |
| `/home/azureuser/agentshield/` | Git repo (run `git log --oneline -10` to check version) |

## Quick Reference — Emergency Commands

```bash
# Restart gateway
sudo systemctl restart hermes-gateway   # or kill + rerun

# Check AgentShield logs only
journalctl -u hermes-gateway -n 200 --no-pager | grep "\[agentshield\]"

# Disable AgentShield temporarily (fail-open — all messages pass)
sed -i 's/enabled: true/enabled: false/' ~/.hermes/agentshield.yaml

# Re-enable
sed -i 's/enabled: false/enabled: true/' ~/.hermes/agentshield.yaml

# Block all new unknown users immediately
sed -i 's/deny_unlisted: false/deny_unlisted: true/' ~/.hermes/agentshield.yaml
```
