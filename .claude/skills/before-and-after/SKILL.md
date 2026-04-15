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

# 6. Mycelium repo path (for the bundled plugin source)
MYCELIUM_REPO=$(pwd)  # assumes running from the mycelium repo
ls "$MYCELIUM_REPO/mycelium-cli/src/mycelium/adapters/openclaw/mycelium/plugin/index.ts" 2>/dev/null \
  && echo "Repo found: $MYCELIUM_REPO" \
  || echo "ERROR: not in the mycelium repo — cd to it first"
```

If any prerequisite fails, fix it before proceeding.

**Throughout this skill, use `$MYCELIUM_API_URL` for all backend requests. Never hardcode a port.**

### 0b. Verify server.mas_id is set

The `mycelium-knowledge-extract` hook reads `server.mas_id` from
`~/.mycelium/config.toml` to know which MAS to ingest into. If it's empty,
every ingest attempt silently falls back to the local log file and nothing
reaches CFN's knowledge graph.

```bash
python3 -c "
import toml, os
cfg = toml.load(os.path.expanduser('~/.mycelium/config.toml'))
mas_id = cfg.get('server', {}).get('mas_id', '')
print(f'mas_id = \"{mas_id}\"')
if not mas_id:
    print('WARNING: mas_id is empty — knowledge ingest will silently fail')
"
```

If `mas_id` is empty, fetch the default MAS for the workspace and set it:

```bash
# List MASes for the configured workspace
WORKSPACE_ID=$(python3 -c "
import toml, os
cfg = toml.load(os.path.expanduser('~/.mycelium/config.toml'))
print(cfg.get('server', {}).get('workspace_id', ''))
")
echo "workspace_id = $WORKSPACE_ID"

# Option A: get mas_id from the active room (if a room is already set)
ACTIVE_ROOM=$(python3 -c "
import toml, os
cfg = toml.load(os.path.expanduser('~/.mycelium/config.toml'))
print(cfg.get('rooms', {}).get('active', ''))
")
if [ -n "$ACTIVE_ROOM" ]; then
    MAS_ID=$(curl -sf "$MYCELIUM_API_URL/rooms/$ACTIVE_ROOM" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(r.get('mas_id') or '')
")
    echo "Room mas_id: $MAS_ID"
fi

# Option B: use mycelium config set
mycelium config set server.mas_id "$MAS_ID"
```

Verify:

```bash
python3 -c "
import toml, os
cfg = toml.load(os.path.expanduser('~/.mycelium/config.toml'))
print('mas_id:', cfg['server']['mas_id'])
"
```

A non-empty `mas_id` here is required for knowledge ingest to work in Phase 3.

**If you just set `mas_id`, restart the gateway now.** The hook process holds
module-level state that isn't flushed on config hot-reload — only a full
restart picks up the new value:

```bash
openclaw gateway restart
```

## Phase 0.5: Choose experiment LLM & API key

Experiment runs get expensive fast. Each scenario fires 10–40+ LLM calls across multi-turn chatter (before case) and negotiation rounds (after case). **Default to haiku** unless the user explicitly wants sonnet — the quality difference for "pick REST vs GraphQL" is indistinguishable, but the cost difference is ~12×.

Before creating agents, use `AskUserQuestion` to ask:

> **Which LLM and API key should the experiment agents use?**
> 1. **Haiku + existing key** *(recommended — ~$0.10–0.30 per full experiment)*
> 2. **Sonnet + existing key** *(flagship model — ~$1.50–4.00 per full experiment)*
> 3. **Different API key or provider** *(isolate experiment cost to a separate key)*

Then set `EXP_MODEL` and, if option 3, `EXP_ANTHROPIC_KEY` (or equivalent) based on the answer:

```bash
# Option 1 (default)
EXP_MODEL="anthropic/claude-haiku-4-5-20251001"

# Option 2
EXP_MODEL="anthropic/claude-sonnet-4-6"

# Option 3 — ask the user for: (a) provider+model string, (b) API key or env var name
EXP_MODEL="anthropic/claude-haiku-4-5-20251001"    # or whatever they specify
export ANTHROPIC_API_KEY="sk-ant-..."              # their separate key; scoped to this shell
```

**Reuse path (default):** If the user picks option 1 or 2, do nothing to the openclaw config — newly-created agents inherit `auth.profiles` from `~/.openclaw/openclaw.json`. Zero setup.

**Override path (option 3):** Export the key in the shell before running `openclaw agents add`. Openclaw agents call LLMs via litellm, which picks up provider env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) automatically. Do NOT write the key into `openclaw.json` — keep it in the shell so it's ephemeral and doesn't touch the user's real config.

Print a one-line summary of the choice so it lands in the transcript:

```bash
echo "Using model: $EXP_MODEL (key: $([ -n "${EXP_ANTHROPIC_KEY:-}" ] && echo 'experiment-scoped' || echo 'openclaw default'))"
```

## Phase 1: Setup

### 1a. Create temporary experiment agents

**Do not reuse existing agents.** Create dedicated temporary agents for the experiment. This avoids clobbering real agent personas and keeps experiments idempotent.

Generate a unique experiment prefix to avoid room/agent name collisions:

```bash
EXP_ID="exp-$(date +%s | tail -c 5)"  # e.g. exp-4821
```

Create agents with `--non-interactive`, using `$EXP_MODEL` from Phase 0.5:

```bash
openclaw agents add "${EXP_ID}-agent-a" \
  --non-interactive \
  --workspace ~/.openclaw/workspaces/${EXP_ID}-agent-a \
  --model "$EXP_MODEL"

openclaw agents add "${EXP_ID}-agent-b" \
  --non-interactive \
  --workspace ~/.openclaw/workspaces/${EXP_ID}-agent-b \
  --model "$EXP_MODEL"
```

For 3+ agent scenarios, create additional agents the same way.

**Never hardcode a model in this skill.** Always use `$EXP_MODEL`. The user picked it in Phase 0.5 for cost reasons — overriding it silently defeats the whole point of asking.

**Disable sandbox mode for experiment agents.** Newly-created agents inherit `agents.defaults.sandbox.mode` from `openclaw.json`, which is typically `"all"` (full sandboxing). Sandboxed agents cannot execute `mycelium session join`, `mycelium negotiate propose`, or `mycelium negotiate respond` because the mycelium CLI binary isn't visible inside the sandbox. The after case will fail silently: agents will dutifully reason about the negotiation in chat, then report "the mycelium CLI isn't available in this environment" — which makes the after case look worse than the before case purely because of a config gotcha.

Patch the sandbox setting for each experiment agent after creation:

```bash
python3 -c "
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
for a in cfg['agents']['list']:
    aid = a.get('id', '')
    if aid.startswith('${EXP_ID}-'):
        a['sandbox'] = {'mode': 'off'}
        print(f'{aid} → sandbox: off')
json.dump(cfg, open(p, 'w'), indent=2)
"
```

This is critical. Without it, the after case is a test of "what happens when agents can't run the CLI they're supposed to run", not a test of the CLI protocol itself.

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

### 1c. Disable the mycelium-bootstrap hook (contamination guard)

The `mycelium-bootstrap` hook is the sole contamination vector. It injects
`MYCELIUM_ROOM_ID` and `MYCELIUM_API_URL` into every agent's environment at
bootstrap — which causes agents in the before case to spontaneously use
`mycelium session join` and `mycelium negotiate` even when the seed says to
just chat.

The `mycelium-room` **channel plugin must stay active** — agents need it to
route messages to each other. Only the bootstrap hook needs to be off.

```bash
openclaw hooks disable mycelium-bootstrap
```

Verify:

```bash
openclaw hooks list 2>&1 | grep -E "mycelium-bootstrap|mycelium-room"
# mycelium-bootstrap should show ⏸ (disabled)
# mycelium-room channel should still be listed as configured
```

### 1d. Configure openclaw.json for the before room

```bash
python3 << 'PYEOF'
import json, os, toml

mycelium_cfg = toml.load(os.path.expanduser("~/.mycelium/config.toml"))
backend_url = mycelium_cfg.get("server", {}).get("api_url", "http://localhost:8000")

oc_path = os.path.expanduser("~/.openclaw/openclaw.json")
with open(oc_path) as f:
    oc = json.load(f)

exp_agents = [os.environ["EXP_AGENT_A"], os.environ["EXP_AGENT_B"]]
room_name = os.environ["EXP_ROOM"]

oc.setdefault("channels", {})["mycelium-room"] = {
    "enabled": True,
    "backendUrl": backend_url,
    "room": room_name,
    "agents": exp_agents,
    "requireMention": True,
}

with open(oc_path, "w") as f:
    json.dump(oc, f, indent=2)

print(f"Channel configured: room={room_name}, agents={exp_agents}, backend={backend_url}")
PYEOF
```

```bash
EXP_AGENT_A="${EXP_ID}-agent-a" \
EXP_AGENT_B="${EXP_ID}-agent-b" \
EXP_ROOM="${EXP_ID}-before" \
python3 << 'PYEOF'
# ... (script above)
PYEOF
```

### 1e. Create experiment rooms and restart gateway

```bash
mycelium room create "${EXP_ID}-before"
mycelium room create "${EXP_ID}-after"
openclaw gateway restart
```

Verify the channel is connected and bootstrap hook is off:

```bash
sleep 4
grep "SSE connected.*${EXP_ID}-before" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1
# Should show: [mycelium-room] SSE connected: {EXP_ID}-before (agents: ...)

openclaw hooks list 2>&1 | grep mycelium-bootstrap
# Should show ⏸ (disabled)
```

## Phase 2: Run "Before" (Channel chat, no bootstrap context)

The channel plugin is active — agents can see each other's messages. The
bootstrap hook is disabled — agents do NOT get `MYCELIUM_ROOM_ID` or
`MYCELIUM_API_URL` injected, so they have no automatic signal to reach for
the Mycelium CLI. This is the true baseline.

### 2a. Seed the conversation

The seed must **explicitly @-mention both agents** (the channel is
`requireMention: true`) AND tell them to reply by @-mentioning each other:

```bash
MENTIONS=$(printf '@%s ' "${EXP_ID}-agent-a" "${EXP_ID}-agent-b")

SEED_BODY="${MENTIONS}

${SCENARIO_PROMPT}

How to work together in this room:
- Reply by @-mentioning the other agent(s) whenever you want them to read and respond. Messages without an @mention are ignored by the channel.
- Keep each message to 2–3 paragraphs.
- Aim for consensus. When you think you've agreed, @-mention the other agent and explicitly say 'I agree' with the final decision.
- Do NOT use any mycelium CLI commands — coordinate only by talking."

curl -sf "$MYCELIUM_API_URL/rooms/${EXP_ID}-before/messages" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,sys; print(json.dumps({'sender_handle':'facilitator','message_type':'broadcast','content':sys.argv[1]}))" "$SEED_BODY")"
```

The `$SCENARIO_PROMPT` is the actual question/decision the agents need to resolve. Keep it focused.

### 2b. Monitor the conversation

```bash
grep "mycelium-room.*←\|mycelium-room.*→" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -20
```

Poll room messages:

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

### 2c. Wait for convergence (and know when to cut it off)

The conversation runs organically — agents see each other's replies and respond. Typical: 3–5 rounds of back-and-forth. Watch for agents settling on a position or explicitly agreeing. Each round takes ~15–20s (agent processing + LLM call + outbound POST).

**Cost guard — critical.** Unstructured agent chat can spiral. Three agents × 10 rounds × haiku context growth adds up fast. Watch for these failure modes and cut the before case off early when you see them:

- **State drift**: agents declare "consensus" multiple times but on different substance (different field lists, different dates, different commitments). If you count ≥3 distinct "CONSENSUS REACHED" messages with ≠ content, the case has failed — there's no single agreed answer and more rounds won't produce one.
- **Scope creep**: the conversation keeps re-opening items that were already settled, with one agent pushing back ("this is the third time you've changed this").
- **Runaway message count**: >30 messages without explicit, unanimous consensus on all required criteria. Every extra message past this is cost with no signal.

**To kill the before case cleanly and stop agents from continuing to burn tokens**, switch the channel away from the before room and restart the gateway. The in-process dispatcher is tied to the SSE subscription — pulling the subscription aborts in-flight dispatches and prevents new ones:

```bash
# Point the channel at the after room (or any other room) to stop the before cascade
python3 -c "
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
cfg['channels']['mycelium-room']['room'] = '${EXP_ID}-after'
json.dump(cfg, open(p, 'w'), indent=2)
"
openclaw gateway restart
```

Alternatively, to stop dispatch without moving to Phase 3 yet, point the channel at a throwaway room name that doesn't exist — the SSE will fail to connect and no messages will be dispatched.

Capture the transcript from the before room **before** you kill the channel, otherwise you'll be writing against a static snapshot while the agents are still generating messages behind you.

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

### 2e. Capture CFN ingest log for the before window

Every time the `mycelium-knowledge-extract` hook fires during the before run
it appends an event to the in-memory buffer on mycelium-backend. Capture the
full buffer to disk so the experiment artifact has a per-event cost trail.

```bash
mycelium cfn log --limit 500 --json > ~/.mycelium/rooms/${EXP_ID}-before/ingest-log.json
mycelium cfn stats --json > ~/.mycelium/rooms/${EXP_ID}-before/ingest-stats.json
```

The `.json` snapshots are what goes into the gist. For human review during
the run, `mycelium cfn log --state=refused,error` is the fast signal on
"did anything blow up here."

## Phase 3: Run "After" (Mycelium Negotiation)

### 3a. Install the Mycelium plugin and configure the channel

Re-enable the bootstrap hook and switch the channel to the after room. The
variable under test is now clearly "with bootstrap context injected" (after)
vs "without" (before) — same channel plugin, same agents, same scenario.

```bash
# Re-enable bootstrap hook — agents now get MYCELIUM_ROOM_ID injected
openclaw hooks enable mycelium-bootstrap

# Switch channel to after room
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

openclaw gateway restart
sleep 4
grep "SSE connected.*${EXP_ID}-after" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1
# Should show: [mycelium-room] SSE connected: {EXP_ID}-after (agents: ...)
```

### 3b. Seed with negotiation instruction

Same scenario, same @-mention pattern — but the instructions tell agents to coordinate via the `mycelium` CLI instead of chatting in the channel:

```bash
MENTIONS=$(printf '@%s ' "${EXP_ID}-agent-a" "${EXP_ID}-agent-b")

SEED_BODY="${MENTIONS}

${SCENARIO_PROMPT}

Use Mycelium structured negotiation to reach consensus. Do NOT discuss this in chat — run these commands instead:

1. Join the coordination session (each of you runs this once with your own handle):
     mycelium session join --handle <your-handle> --room ${EXP_ID}-after -m \"<your position in one sentence>\"

2. Wait for CognitiveEngine to address you. It will send a tick message telling you your turn, the current offer, and whether to 'propose' or 'respond'.

3. Respond via the CLI:
     mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... --room ${EXP_ID}-after --handle <your-handle>
     mycelium negotiate respond accept --room ${EXP_ID}-after --handle <your-handle>
     mycelium negotiate respond reject --room ${EXP_ID}-after --handle <your-handle>

Explain your reasoning briefly in chat before each CLI command so the human can follow along. Repeat until you receive a consensus message."

curl -sf "$MYCELIUM_API_URL/rooms/${EXP_ID}-after/messages" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,sys; print(json.dumps({'sender_handle':'facilitator','message_type':'broadcast','content':sys.argv[1]}))" "$SEED_BODY")"
```

### 3c. Wait for the full flow

The automated sequence:
1. Agents receive seed → execute `mycelium session join` (~15s)
2. Join window closes → CFN fires (~30s after first join)
3. Channel plugin polls, detects session sub-room → subscribes SSE (~5s)
4. CognitiveEngine posts ticks → plugin formats and dispatches to agents
5. Agents receive ticks, reason about the offer, execute `mycelium negotiate propose/respond`
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

### 3e. Capture CFN ingest log for the after window

Mirrors Phase 2e. Snapshot the full buffer + stats for the after run so the
gist carries both-case cost evidence.

```bash
mycelium cfn log --limit 500 --json > ~/.mycelium/rooms/${EXP_ID}-after/ingest-log.json
mycelium cfn stats --json > ~/.mycelium/rooms/${EXP_ID}-after/ingest-stats.json
```

**Important**: the in-memory buffer is shared across both runs and resets
only on backend restart. If you don't snapshot after Phase 2 (before) and
again after Phase 3 (after), you'll lose the separation. Phase 2e + 3e
ordering matters — each snapshot captures everything seen so far, and you
diff them in Phase 4 to get the per-run cost.

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

### CFN ingest activity (per-run cost delta)

Diff `ingest-stats.json` between the two runs and render the delta. Use
this block to catch cost regressions: if the `after` case ingests 10x the
tokens of `before` for the same scenario, something's wrong upstream of
the dedupe + circuit breaker.

```bash
python3 - <<'PY'
import json, pathlib
exp = "${EXP_ID}"
for label in ("before", "after"):
    p = pathlib.Path(f"~/.mycelium/rooms/{exp}-{label}/ingest-stats.json").expanduser()
    if not p.exists():
        print(f"{label}: (missing)"); continue
    d = json.loads(p.read_text())
    t = d.get("total", {})
    print(f"{label}: events={t.get('events',0)} "
          f"tokens≈{t.get('estimated_cfn_knowledge_input_tokens',0):,} "
          f"bytes={t.get('payload_bytes',0):,}")
PY
```

| Metric | Before | After | Delta |
|---|---|---|---|
| Ingest events | ... | ... | +/-N |
| Est. input tokens | ~... | ~... | +/-N% |
| Refused (circuit breaker) | ... | ... | ... |
| Deduped (hash hit) | ... | ... | ... |
| Errors | ... | ... | ... |

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

## Phase 4b: (optional) Share results as a gist

Experiment artifacts (the evaluation report, both transcripts, and the session sub-room transcript) are often worth sharing with teammates — for PR discussions, roadmap meetings, or just "hey look at this failure mode." Inline posting hits GitHub's 65,536-char comment limit fast; gists are the cleanest path.

**Before creating a gist, scan for secrets.** Agent narration can leak absolute home paths, API keys from shell env, or session tokens if anything weird happened. Grep for the obvious patterns:

```bash
for f in ~/.mycelium/rooms/${EXP_ID}/evaluation.md \
         ~/.mycelium/rooms/${EXP_ID}-before/transcript.md \
         ~/.mycelium/rooms/${EXP_ID}-after/transcript.md \
         ~/.mycelium/rooms/${EXP_ID}-after/session-transcript.md \
         ~/.mycelium/rooms/${EXP_ID}-before/ingest-log.json \
         ~/.mycelium/rooms/${EXP_ID}-after/ingest-log.json \
         ~/.mycelium/rooms/${EXP_ID}-before/ingest-stats.json \
         ~/.mycelium/rooms/${EXP_ID}-after/ingest-stats.json; do
  [ -f "$f" ] || continue
  echo "=== $f ==="
  grep -inE 'sk-[a-z0-9]|ghp_|gho_|bearer [a-z0-9]|api[_-]?key.*[=:]|password.*[=:]|/Users/|/home/' "$f" | head -5 || echo "  (clean)"
done
```

The ingest-log JSON files are particularly worth scanning — they include
the full payload content that was forwarded to CFN, which for agent turns
may include filesystem paths, shell output, or tool results. Err on the
side of redacting.

If anything lights up, either redact or skip the gist. **Always ask the user before uploading** — even a private gist is a URL someone could share, and experiment transcripts may contain persona content or internal scenario details that weren't meant to leave the machine.

Once clean, create a secret gist (URL-only, not listed on your profile).

**Watch out for filename collisions.** `gh gist create` uses the file's basename, so `~/.mycelium/rooms/${EXP_ID}-before/transcript.md` and `~/.mycelium/rooms/${EXP_ID}-after/transcript.md` both become `transcript.md` and the second one silently overwrites the first. Stage the files under unique names in a temp directory first:

```bash
STAGE=$(mktemp -d)
cp ~/.mycelium/rooms/${EXP_ID}/evaluation.md               "$STAGE/evaluation.md"
cp ~/.mycelium/rooms/${EXP_ID}-before/transcript.md        "$STAGE/before-transcript.md"
cp ~/.mycelium/rooms/${EXP_ID}-after/transcript.md         "$STAGE/after-transcript.md"
cp ~/.mycelium/rooms/${EXP_ID}-after/session-transcript.md "$STAGE/after-session-transcript.md"
# Ingest logs — skip silently if a snapshot is missing (e.g. ran --before-only)
cp ~/.mycelium/rooms/${EXP_ID}-before/ingest-log.json      "$STAGE/before-ingest-log.json" 2>/dev/null || true
cp ~/.mycelium/rooms/${EXP_ID}-before/ingest-stats.json    "$STAGE/before-ingest-stats.json" 2>/dev/null || true
cp ~/.mycelium/rooms/${EXP_ID}-after/ingest-log.json       "$STAGE/after-ingest-log.json" 2>/dev/null || true
cp ~/.mycelium/rooms/${EXP_ID}-after/ingest-stats.json     "$STAGE/after-ingest-stats.json" 2>/dev/null || true

gh gist create \
  -d "${EXP_ID}: ${SCENARIO_NAME} — before-and-after" \
  "$STAGE"/*
```

The command prints the gist URL. Use it in a PR comment (`gh pr comment <N> --body "..."`) or Slack message with a short summary and the link — keep the comment body concise and put the full artifacts behind the gist link. Example PR comment body:

```markdown
## Experiment: ${EXP_ID} — ${SCENARIO_NAME}

<3-line top-line finding>

| Metric | Before | After |
|---|---|---|
| <key stat 1> | ... | ... |
| <key stat 2> | ... | ... |

Full artifacts (evaluation + both transcripts + session sub-room):
<gist URL>
```

Notes:
- `gh gist create` defaults to secret. Pass `--public` only if the user explicitly asks.
- Gists support multiple files in one upload — keep related artifacts together.
- The gist URL is permanent; link to it from commit messages or issue comments as needed.
- GitHub does not support file attachments via `gh` CLI for PR/issue comments. Drag-and-drop upload in the web UI is the only native "attachment" path, and it can't be scripted. Gists are the closest scriptable alternative.

## Phase 5: Cleanup

Remove temporary agents and experiment rooms, restore hook state:

```bash
# Remove temp agents and channel config
python3 -c "
import json, os
oc_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(oc_path) as f:
    oc = json.load(f)
oc['agents']['list'] = [a for a in oc.get('agents', {}).get('list', []) if not a.get('id', '').startswith('${EXP_ID}')]
oc.get('channels', {}).pop('mycelium-room', None)
with open(oc_path, 'w') as f:
    json.dump(oc, f, indent=2)
print('Agents and channel config removed')
"

# Delete agent workspaces
rm -rf ~/.openclaw/workspaces/${EXP_ID}-*
rm -rf ~/.openclaw/agents/${EXP_ID}-*

# Ensure hooks are back to their normal state
openclaw hooks enable mycelium-bootstrap
openclaw hooks enable mycelium-knowledge-extract

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
| After-case agents say "mycelium CLI isn't available in this environment" | Experiment agents are sandboxed, so they can't see the `mycelium` binary | Set `sandbox: {mode: "off"}` on each `exp-*` agent in `openclaw.json` and restart the gateway. See Phase 1a. |

## Future

- **Automated room switching**: Avoid gateway restart between before/after runs
- **Statistical rigor**: Run same scenario multiple times to control for LLM variance
- **3+ agent scenarios**: Test with larger groups
- **CFN graph diff**: Render a concept-level diff between pre-run and post-run
  `mycelium cfn ls` snapshots so reviewers can see exactly which concepts
  CFN extracted as a result of the experiment

## Tips

- Strong persona conflicts produce the most interesting comparisons
- Specific memories ground agents — "60% reduction in integration time" beats "it was faster"
- Success criteria should be measurable — "includes migration path" not "good plan"
- Start with 2 agents, add more once the flow is validated
- The "before" case should be fair — if unstructured conversation works, that's valid data
- Each experiment takes ~5-10 minutes (before: ~2 min, after: ~5 min, eval: ~1 min)
