---
name: before-and-after
description: A/B test multi-agent consensus quality with and without Mycelium's structured negotiation. Uses real OpenClaw agents talking through a Mycelium room channel. Handles full setup if needed.
argument-hint: "<scenario description or experiment file>"
---

# Before-and-After Consensus Testing

Compare how real OpenClaw agents reach consensus **with and without** Mycelium's CognitiveEngine. Same agents, same personas, same scenario — two coordination approaches.

**You are the test harness.** You set up the infrastructure, seed scenarios, observe transcripts, and evaluate. The agents do the actual negotiating.

## Phase 0: Prerequisites Check

Before anything else, verify the stack. Run each check and stop if any fail.

```bash
# 1. Mycelium CLI
mycelium --version
# If missing: pip install mycelium (or pipx install mycelium)

# 2. Mycelium stack running
curl -sf http://localhost:8001/health | python3 -m json.tool
# Should show status=ok. If not: mycelium install && mycelium up
# Note: the port may differ — check ~/.mycelium/config.toml [server] api_url

# 3. OpenClaw installed
openclaw --version
# If missing: npm install -g openclaw (or see https://docs.openclaw.ai)

# 4. OpenClaw gateway running
openclaw channels status
# Should show "Gateway reachable". If not: openclaw gateway start

# 5. OpenClaw agents exist
openclaw agents list
# Need at least 2 agents. If missing, create them (see Phase 1).
```

If any prerequisite fails, fix it before proceeding. The skill needs all of these running.

## Phase 1: Setup

### 1a. Ensure OpenClaw agents exist

Check `openclaw agents list`. You need at least 2 agents. If they don't exist:

```bash
openclaw agents add agent-alpha
openclaw agents add agent-beta
# Creates workspaces at ~/.openclaw/workspaces/{name}/
```

Record which agents you're using — you'll need their IDs for the channel config.

### 1b. Write personas

Each agent needs a SOUL.md in their workspace that defines who they are for this experiment. **Back up any existing SOUL.md first.**

```bash
# Back up existing personas
cp ~/.openclaw/workspaces/{agent}/SOUL.md ~/.openclaw/workspaces/{agent}/SOUL.md.bak 2>/dev/null

# Write experiment persona
cat > ~/.openclaw/workspaces/{agent}/SOUL.md << 'EOF'
{persona text here — who they are, what they value, what they know}
EOF
```

Derive personas from the user's scenario. Strong conflicts produce the most interesting comparisons. Include specific memories/data points, not just vague personality descriptions.

### 1c. Install the mycelium-channel plugin

Check if already installed:

```bash
ls ~/.openclaw/extensions/mycelium-channel/openclaw.plugin.json 2>/dev/null && echo "installed" || echo "not installed"
```

If not installed, copy from the repo and create the manifest:

```bash
# Create plugin directory
mkdir -p ~/.openclaw/extensions/mycelium-channel

# Copy plugin source from the mycelium repo
cp /path/to/mycelium/openclaw-channel-plugin/src/channel-plugin.ts ~/.openclaw/extensions/mycelium-channel/index.ts

# Create package.json
cat > ~/.openclaw/extensions/mycelium-channel/package.json << 'EOF'
{
  "name": "mycelium-channel",
  "version": "0.1.0",
  "type": "module",
  "openclaw": {
    "extensions": ["./index.ts"],
    "channel": {
      "id": "mycelium-room",
      "label": "Mycelium Room",
      "selectionLabel": "Mycelium Room (shared coordination channel)"
    }
  }
}
EOF

# Create plugin manifest
cat > ~/.openclaw/extensions/mycelium-channel/openclaw.plugin.json << 'EOF'
{
  "id": "mycelium-channel",
  "name": "Mycelium Channel",
  "description": "Room-based agent coordination via Mycelium",
  "version": "0.1.0",
  "kind": "channel",
  "channels": ["mycelium-room"],
  "configSchema": {}
}
EOF
```

### 1d. Configure openclaw.json

The channel plugin needs to be registered and the channel configured. Read `~/.openclaw/openclaw.json` and ensure these sections exist:

**In `plugins.entries`:**
```json
"mycelium-channel": { "enabled": true }
```

**In `plugins.allow`:**
```json
["mycelium-channel"]
```

**In `plugins.load.paths`:**
```json
["/Users/{you}/.openclaw/extensions/mycelium-channel"]
```

**In `channels`:**
```json
"mycelium-room": {
  "enabled": true,
  "backendUrl": "http://localhost:8001",
  "room": "{room-name}",
  "agents": ["{agent-1-id}", "{agent-2-id}"]
}
```

The `backendUrl` should match the mycelium backend's published port (check `~/.mycelium/config.toml` → `server.api_url`). The `agents` array lists the OpenClaw agent IDs that will participate.

**Important:** Use `python3` or `node` to edit the JSON programmatically — don't hand-edit and risk breaking it.

### 1e. Create experiment rooms

```bash
mycelium room create {name}-before
mycelium room create {name}-after
```

### 1f. Restart gateway

```bash
openclaw gateway restart
```

Verify the channel loaded:

```bash
openclaw channels status
# Should show "Mycelium Room default: enabled, configured"
```

Check logs for SSE connection:

```bash
grep "mycelium-room.*SSE connected" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1
```

## Phase 2: Run "Before" (Unstructured Channel)

### 2a. Point channel at the "before" room

Edit `channels.mycelium-room.room` in `~/.openclaw/openclaw.json` to the before room name. Restart gateway.

### 2b. Seed the conversation

```bash
curl -sf http://localhost:8001/rooms/{name}-before/messages \
  -H "Content-Type: application/json" \
  -d '{"sender_handle": "facilitator", "message_type": "broadcast", "content": "{scenario prompt — tell agents to discuss and reach agreement, keep responses to 2-3 paragraphs}"}'
```

### 2c. Monitor

Watch gateway logs for the conversation:

```bash
grep "mycelium-room.*←\|mycelium-room.*→" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -20
```

Or poll room messages:

```bash
curl -sf "http://localhost:8001/rooms/{name}-before/messages?limit=20" | python3 -m json.tool
```

### 2d. Wait for convergence

The conversation runs organically — agents see each other's replies and respond. Typical: 3-5 rounds of back-and-forth. Watch for agents settling on a position or explicitly agreeing.

### 2e. Capture transcript

```bash
curl -sf "http://localhost:8001/rooms/{name}-before/messages?limit=50" | python3 -c "
import sys, json
data = json.load(sys.stdin)
msgs = data.get('messages', data) if isinstance(data, dict) else data
if isinstance(msgs, list):
    msgs.reverse()
    for m in msgs:
        print(f'**{m[\"sender_handle\"]}:**')
        print(m['content'])
        print()
" > ~/.mycelium/rooms/{name}-before/transcript.md
```

## Phase 3: Run "After" (Mycelium Negotiation)

### 3a. Point channel at the "after" room

Edit `channels.mycelium-room.room` in `~/.openclaw/openclaw.json` to the after room name. Restart gateway.

### 3b. Seed with negotiation instruction

```bash
curl -sf http://localhost:8001/rooms/{name}-after/messages \
  -H "Content-Type: application/json" \
  -d '{"sender_handle": "facilitator", "message_type": "broadcast", "content": "{same scenario as before}\n\nUse mycelium structured negotiation. Run:\n  mycelium session join --handle <your-handle> --room {name}-after -m \"<your position>\"\nThen wait for CognitiveEngine ticks and respond with mycelium message propose/respond commands."}'
```

### 3c. Wait for the full flow

The automated sequence:
1. Agents receive seed → execute `mycelium session join` (~15s)
2. Join window closes → CFN fires (~30s after first join)
3. Channel plugin detects session sub-room → subscribes SSE (~5s poll)
4. CognitiveEngine posts ticks → plugin dispatches to agents
5. Agents receive ticks, execute `mycelium message propose/respond`
6. Rounds continue until consensus or timeout

Monitor with:

```bash
# Watch for tick delivery
grep "mycelium-room.*🎯\|mycelium-room.*🤝" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -20

# Check session state
curl -sf "http://localhost:8001/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '{name}-after' in r['name']:
        print(f'{r[\"name\"]}: {r.get(\"coordination_state\", \"none\")}')
"
```

### 3d. Capture transcript

When consensus is reached (🤝 log) or the session completes:

```bash
# Room messages (agent chat + join confirmations)
curl -sf "http://localhost:8001/rooms/{name}-after/messages?limit=50" > /tmp/after-room.json

# Session room messages (ticks, proposals, consensus)
SESSION_ROOM=$(curl -sf "http://localhost:8001/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '{name}-after:session:' in r['name']:
        print(r['name']); break
")
curl -sf "http://localhost:8001/rooms/$SESSION_ROOM/messages?limit=100" > /tmp/after-session.json
```

## Phase 4: Evaluate

Compare both transcripts against the success criteria. Score each criterion 1-5:

| Score | Meaning |
|-------|---------|
| 1 | Not addressed at all |
| 2 | Mentioned but unresolved |
| 3 | Partially addressed |
| 4 | Substantially addressed |
| 5 | Fully resolved |

Write the comparison report to `~/.mycelium/rooms/{name}/evaluation.md`:

```markdown
## Before-and-After: {scenario name}

### Summary
| Metric | Before (Channel) | After (Mycelium) |
|--------|-------------------|-------------------|
| Consensus reached? | ... | ... |
| Rounds to resolution | ... | ... |
| Issues explicitly identified | ... | ... |
| Issues resolved | ... | ... |
| Specific assignments made | ... | ... |
| Overall score | X/5 | X/5 |

### Success Criteria
| Criterion | Before | After | Delta |
|-----------|--------|-------|-------|
| ... | X/5 | X/5 | +/-N |

### Qualitative Analysis
...

### Verdict
{honest assessment}
```

## Phase 5: Cleanup

```bash
# Restore original SOUL.md files
cp ~/.openclaw/workspaces/{agent}/SOUL.md.bak ~/.openclaw/workspaces/{agent}/SOUL.md 2>/dev/null

# Optionally delete test rooms
curl -sf -X DELETE http://localhost:8001/rooms/{name}-before
curl -sf -X DELETE http://localhost:8001/rooms/{name}-after

# Restore openclaw.json channel room to original value (or remove mycelium-room channel)
```

## Input

Describe the scenario however you want. Extract:

- **Scenario**: What are the agents deciding?
- **Agents**: Which OpenClaw agents to use and what personas to give them
- **Success criteria**: What does a good outcome look like?

For batch runs, provide a JSON file with an `experiments` array. Schema is loose — fill gaps with defaults:

```json
{
  "experiments": [
    {
      "name": "sprint-priorities",
      "description": "Agree on Q3 priorities",
      "agents": [
        { "handle": "julia-agent", "persona": "Backend engineer, values reliability", "position": "DB migration first" },
        { "handle": "selina-agent", "persona": "PM, wants to ship fast", "position": "Onboarding in 3 weeks" }
      ],
      "success_criteria": ["Concrete timeline", "Both concerns addressed"]
    }
  ]
}
```

## Flags

- `--before-only` — Run only the unstructured case
- `--after-only` — Run only the Mycelium negotiation case
- `--eval-only` — Skip both runs, evaluate existing transcripts
- `--setup-only` — Just configure the channel plugin and agents, don't run experiments
- No flags — full run: setup → before → after → evaluate

## Future

- **Knowledge extraction**: Evaluate memories generated via `mycelium-knowledge-extract` hook
- **Automated room switching**: Avoid editing openclaw.json manually between runs
- **Statistical rigor**: Run same scenario multiple times to control for LLM variance
- **3+ agent scenarios**: Test with larger groups

## Tips

- Strong persona conflicts produce the most interesting comparisons
- Specific memories ground agents — "3 outages last quarter" beats "values reliability"
- Success criteria should be measurable — "includes week-level timeline" not "good plan"
- Start with 2 agents, add more once the flow is validated
- The "before" case should be fair — if unstructured conversation works, that's valid data
