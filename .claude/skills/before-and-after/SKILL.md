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

# 2. Resolve the backend URL — NEVER hardcode a port
MYCELIUM_API_URL=$(python3 -c "
import toml, os
cfg_path = os.path.expanduser('~/.mycelium/config.toml')
cfg = toml.load(cfg_path)
print(cfg.get('server', {}).get('api_url', 'http://localhost:8000'))
")
echo "Backend URL: $MYCELIUM_API_URL"

# 3. Mycelium stack running
curl -sf "$MYCELIUM_API_URL/health" | python3 -m json.tool
# Should show status=ok. If not: mycelium install && mycelium up

# 4. OpenClaw installed
openclaw --version
# If missing: npm install -g openclaw (or see https://docs.openclaw.ai)

# 5. OpenClaw gateway running
openclaw channels status
# Should show "Gateway reachable" in the output. If not: openclaw gateway start

# 6. Mycelium repo path (for the channel plugin source)
MYCELIUM_REPO=$(pwd)  # assumes running from the mycelium repo
ls "$MYCELIUM_REPO/openclaw-channel-plugin/src/channel-plugin.ts" 2>/dev/null \
  && echo "Repo found: $MYCELIUM_REPO" \
  || echo "ERROR: not in the mycelium repo — cd to it first"
```

If any prerequisite fails, fix it before proceeding.

**Throughout this skill, use `$MYCELIUM_API_URL` for all backend requests. Never hardcode a port.**

## Phase 1: Setup

### 1a. Create temporary experiment agents

**Do not reuse existing agents.** Create dedicated temporary agents for the experiment. This avoids clobbering real agent personas and keeps experiments idempotent.

Generate a unique experiment prefix to avoid room/agent name collisions:

```bash
EXP_ID="exp-$(date +%s | tail -c 5)"  # e.g. exp-4821
```

Create agents with `--non-interactive`:

```bash
openclaw agents add "${EXP_ID}-agent-a" \
  --non-interactive \
  --workspace ~/.openclaw/workspaces/${EXP_ID}-agent-a \
  --model anthropic/claude-sonnet-4-6

openclaw agents add "${EXP_ID}-agent-b" \
  --non-interactive \
  --workspace ~/.openclaw/workspaces/${EXP_ID}-agent-b \
  --model anthropic/claude-sonnet-4-6
```

For 3+ agent scenarios, create additional agents the same way.

### 1b. Write personas

Derive personas from the user's scenario. Write a SOUL.md for each agent:

```bash
cat > ~/.openclaw/workspaces/${EXP_ID}-agent-a/SOUL.md << 'EOF'
{persona text — who they are, what they value, specific experience/data}
EOF

cat > ~/.openclaw/workspaces/${EXP_ID}-agent-b/SOUL.md << 'EOF'
{persona text — who they are, what they value, specific experience/data}
EOF
```

Good personas include:
- Concrete experience ("10 years building REST APIs", not just "likes REST")
- Specific data points ("60% reduction in integration time", not "it was faster")
- Clear priorities and red lines ("won't compromise on caching", not "prefers performance")

### 1c. Install the mycelium-channel plugin

Check if already installed:

```bash
ls ~/.openclaw/extensions/mycelium-channel/openclaw.plugin.json 2>/dev/null \
  && echo "Channel plugin already installed" \
  || echo "Channel plugin needs installation"
```

If not installed:

```bash
mkdir -p ~/.openclaw/extensions/mycelium-channel

# Copy plugin source from the mycelium repo
cp "$MYCELIUM_REPO/openclaw-channel-plugin/src/channel-plugin.ts" \
   ~/.openclaw/extensions/mycelium-channel/index.ts

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

Use Python to safely edit the JSON. This ensures the plugin is registered, allowed, and the channel is configured with the correct backend URL and agent list:

```python
python3 << 'PYEOF'
import json, os, toml

# Read mycelium backend URL
mycelium_cfg = toml.load(os.path.expanduser("~/.mycelium/config.toml"))
backend_url = mycelium_cfg.get("server", {}).get("api_url", "http://localhost:8000")

# Read current openclaw config
oc_path = os.path.expanduser("~/.openclaw/openclaw.json")
with open(oc_path) as f:
    oc = json.load(f)

# Experiment config — replace EXP_ID and ROOM_NAME before running
exp_agents = [os.environ.get("EXP_AGENT_A", "FIXME"), os.environ.get("EXP_AGENT_B", "FIXME")]
room_name = os.environ.get("EXP_ROOM", "FIXME")

# Ensure plugin entries
oc.setdefault("plugins", {}).setdefault("entries", {})["mycelium-channel"] = {"enabled": True}

# Ensure plugin allow list
allow = oc["plugins"].setdefault("allow", [])
if "mycelium-channel" not in allow:
    allow.append("mycelium-channel")

# Ensure plugin load path
ext_path = os.path.expanduser("~/.openclaw/extensions/mycelium-channel")
load_paths = oc["plugins"].setdefault("load", {}).setdefault("paths", [])
if ext_path not in load_paths:
    load_paths.append(ext_path)

# Set channel config
oc.setdefault("channels", {})["mycelium-room"] = {
    "enabled": True,
    "backendUrl": backend_url,
    "room": room_name,
    "agents": exp_agents,
}

with open(oc_path, "w") as f:
    json.dump(oc, f, indent=2)

print(f"Config updated: room={room_name}, agents={exp_agents}, backend={backend_url}")
PYEOF
```

Call it with environment variables:

```bash
EXP_AGENT_A="${EXP_ID}-agent-a" \
EXP_AGENT_B="${EXP_ID}-agent-b" \
EXP_ROOM="${EXP_ID}-before" \
python3 << 'PYEOF'
# ... (the script above)
PYEOF
```

### 1e. Create experiment rooms

Use the experiment prefix to avoid collisions:

```bash
mycelium room create "${EXP_ID}-before"
mycelium room create "${EXP_ID}-after"
```

### 1f. Restart gateway and verify

```bash
openclaw gateway restart
```

Verify:

```bash
# Check gateway log for SSE connection to the room
grep "mycelium-room.*SSE connected" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1
# Should show: SSE connected: {EXP_ID}-before (agents: {EXP_ID}-agent-a, {EXP_ID}-agent-b)
```

## Phase 2: Run "Before" (Unstructured Channel)

The channel should already be pointing at the "before" room from Phase 1d.

### 2a. Seed the conversation

```bash
curl -sf "$MYCELIUM_API_URL/rooms/${EXP_ID}-before/messages" \
  -H "Content-Type: application/json" \
  -d "{\"sender_handle\": \"facilitator\", \"message_type\": \"broadcast\", \"content\": \"$SCENARIO_PROMPT\"}"
```

The `$SCENARIO_PROMPT` should tell agents to discuss and reach agreement. Include the scenario, ask them to keep responses to 2-3 paragraphs.

### 2b. Monitor the conversation

Watch gateway logs for inbound/outbound:

```bash
grep "mycelium-room.*←\|mycelium-room.*→" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -20
```

Or poll room messages:

```bash
curl -sf "$MYCELIUM_API_URL/rooms/${EXP_ID}-before/messages?limit=20" | python3 -c "
import sys, json
data = json.load(sys.stdin)
msgs = data.get('messages', data) if isinstance(data, dict) else data
if isinstance(msgs, list):
    msgs.reverse()
    for m in msgs:
        print(f'[{m[\"sender_handle\"]}] {m[\"content\"][:120]}')
        print()
"
```

### 2c. Wait for convergence

The conversation runs organically — agents see each other's replies and respond. Typical: 3-5 rounds of back-and-forth. Watch for agents settling on a position or explicitly agreeing. Each round takes ~15-20s (agent processing + LLM call + outbound POST).

### 2d. Capture transcript

```bash
curl -sf "$MYCELIUM_API_URL/rooms/${EXP_ID}-before/messages?limit=50" | python3 -c "
import sys, json
data = json.load(sys.stdin)
msgs = data.get('messages', data) if isinstance(data, dict) else data
if isinstance(msgs, list):
    msgs.reverse()
    lines = []
    for m in msgs:
        lines.append(f'**{m[\"sender_handle\"]}:**')
        lines.append(m['content'])
        lines.append('')
    print('\n'.join(lines))
" > ~/.mycelium/rooms/${EXP_ID}-before/transcript.md
```

## Phase 3: Run "After" (Mycelium Negotiation)

### 3a. Switch channel to the "after" room

```python
python3 -c "
import json, os
oc_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(oc_path) as f:
    oc = json.load(f)
oc['channels']['mycelium-room']['room'] = '${EXP_ID}-after'
with open(oc_path, 'w') as f:
    json.dump(oc, f, indent=2)
print('Switched to ${EXP_ID}-after')
"
```

```bash
openclaw gateway restart
```

Verify SSE connected to the new room:

```bash
grep "SSE connected.*${EXP_ID}-after" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1
```

### 3b. Seed with negotiation instruction

Same scenario but tell agents to use mycelium:

```bash
curl -sf "$MYCELIUM_API_URL/rooms/${EXP_ID}-after/messages" \
  -H "Content-Type: application/json" \
  -d "{\"sender_handle\": \"facilitator\", \"message_type\": \"broadcast\", \"content\": \"$SCENARIO_PROMPT\n\nUse mycelium structured negotiation to reach consensus. Run:\n  mycelium session join --handle <your-handle> --room ${EXP_ID}-after -m \\\"<your position>\\\"\nThen wait for CognitiveEngine ticks and respond with mycelium message propose/respond commands. Explain your reasoning before each command.\"}"
```

### 3c. Wait for the full flow

The automated sequence:
1. Agents receive seed → execute `mycelium session join` (~15s)
2. Join window closes → CFN fires (~30s after first join)
3. Channel plugin polls, detects session sub-room → subscribes SSE (~5s)
4. CognitiveEngine posts ticks → plugin formats and dispatches to agents
5. Agents receive ticks, reason about the offer, execute `mycelium message propose/respond`
6. Backend collects responses → calls CFN `/decide` → next round
7. Repeat until consensus or timeout (max ~20 rounds)

Monitor:

```bash
# Tick delivery (🎯) and consensus (🤝)
grep "mycelium-room.*🎯\|mycelium-room.*🤝" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -20

# Session state
curl -sf "$MYCELIUM_API_URL/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '${EXP_ID}-after' in r['name']:
        print(f'{r[\"name\"]}: {r.get(\"coordination_state\", \"none\")}')
"
```

### 3d. Capture transcript

When consensus is reached or the session completes:

```bash
# Room messages
curl -sf "$MYCELIUM_API_URL/rooms/${EXP_ID}-after/messages?limit=50" | python3 -c "
import sys, json
data = json.load(sys.stdin)
msgs = data.get('messages', data) if isinstance(data, dict) else data
if isinstance(msgs, list):
    msgs.reverse()
    for m in msgs:
        print(f'**{m[\"sender_handle\"]}:**')
        print(m['content'])
        print()
" > ~/.mycelium/rooms/${EXP_ID}-after/transcript.md

# Session room messages (ticks, proposals, consensus)
SESSION_ROOM=$(curl -sf "$MYCELIUM_API_URL/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '${EXP_ID}-after:session:' in r['name']:
        print(r['name']); break
")
echo "Session room: $SESSION_ROOM"
curl -sf "$MYCELIUM_API_URL/rooms/$SESSION_ROOM/messages?limit=100" | python3 -c "
import sys, json
data = json.load(sys.stdin)
msgs = data.get('messages', data) if isinstance(data, dict) else data
if isinstance(msgs, list):
    msgs.reverse()
    for m in msgs:
        mt = m['message_type']
        sh = m.get('sender_handle', '')
        c = str(m['content'])[:200]
        print(f'[{mt}] {sh}: {c}')
        print()
" > ~/.mycelium/rooms/${EXP_ID}-after/session-transcript.md
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

Write the comparison report to `~/.mycelium/rooms/${EXP_ID}/evaluation.md`:

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

**Before (unstructured channel):**
- What worked: ...
- What failed: ...
- Failure modes: ...

**After (Mycelium-mediated):**
- What worked: ...
- What failed: ...
- Value added by CognitiveEngine: ...

### Verdict
{honest assessment — if before beat after, say so}
```

## Phase 5: Cleanup

Remove temporary agents and experiment rooms:

```bash
# Remove temporary agents from openclaw config
python3 -c "
import json, os
oc_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(oc_path) as f:
    oc = json.load(f)
oc['agents']['list'] = [a for a in oc.get('agents', {}).get('list', []) if not a.get('id', '').startswith('${EXP_ID}')]
# Remove channel config (or restore to previous room)
oc.get('channels', {}).pop('mycelium-room', None)
with open(oc_path, 'w') as f:
    json.dump(oc, f, indent=2)
print('Agents and channel config removed')
"

# Delete agent workspaces
rm -rf ~/.openclaw/workspaces/${EXP_ID}-*
rm -rf ~/.openclaw/agents/${EXP_ID}-*

# Delete experiment rooms
curl -sf -X DELETE "$MYCELIUM_API_URL/rooms/${EXP_ID}-before"
curl -sf -X DELETE "$MYCELIUM_API_URL/rooms/${EXP_ID}-after"

# Restart gateway to pick up config changes
openclaw gateway restart
```

## Input

Describe the scenario however you want. Extract:

- **Scenario**: What are the agents deciding?
- **Agents**: How many, and what personas to give them
- **Success criteria**: What does a good outcome look like?

For batch runs, provide a JSON file with an `experiments` array. Schema is loose — fill gaps with defaults:

```json
{
  "experiments": [
    {
      "name": "api-design",
      "description": "REST vs GraphQL for the developer platform",
      "agents": [
        { "persona": "Backend architect, REST purist, 10 years experience", "position": "REST with OpenAPI" },
        { "persona": "Frontend lead, tired of over-fetching", "position": "GraphQL for everything" }
      ],
      "success_criteria": ["Clear decision on approach", "Migration path defined", "Both performance and DX addressed"]
    }
  ]
}
```

## Flags

- `--before-only` — Run only the unstructured case
- `--after-only` — Run only the Mycelium negotiation case
- `--eval-only` — Skip both runs, evaluate existing transcripts
- `--setup-only` — Just configure agents and channel, don't run experiments
- No flags — full run: setup → before → after → evaluate → cleanup

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| `openclaw agents add` prompts interactively | Missing `--non-interactive` | Add `--non-interactive --workspace <path>` |
| `mycelium room create` returns 400 | Room name already exists | Use unique `$EXP_ID` prefix or delete existing room first |
| No SSE connection in logs | Channel plugin not loaded | Check `openclaw.plugin.json` exists, plugin in `load.paths` and `allow` |
| Agents don't respond to seed | Channel config wrong room/agents | Verify `channels.mycelium-room` in openclaw.json matches the experiment |
| Ticks never arrive (after case) | Session room SSE not subscribed | Check poll found session room; verify CFN is running (`docker logs mycelium-backend`) |
| Agent processes hang | `--local` flag or SSE loop in child | Ensure NOT using `--local`; check `MYCELIUM_CHANNEL_ONESHOT` env var |
| `curl` to backend fails | Wrong port | Read port from `~/.mycelium/config.toml`, don't hardcode |

## Future

- **Knowledge extraction**: Evaluate memories generated via `mycelium-knowledge-extract` hook
- **Automated room switching**: Avoid gateway restart between before/after runs
- **Statistical rigor**: Run same scenario multiple times to control for LLM variance
- **3+ agent scenarios**: Test with larger groups

## Tips

- Strong persona conflicts produce the most interesting comparisons
- Specific memories ground agents — "60% reduction in integration time" beats "it was faster"
- Success criteria should be measurable — "includes migration path" not "good plan"
- Start with 2 agents, add more once the flow is validated
- The "before" case should be fair — if unstructured conversation works, that's valid data
- Each experiment takes ~5-10 minutes (before: ~2 min, after: ~5 min, eval: ~1 min)
