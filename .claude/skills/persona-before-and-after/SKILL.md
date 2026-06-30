---
name: persona-before-and-after
description: A/B test multi-agent consensus quality with and without Mycelium's structured negotiation, using fully-composed agent personas from the agent-personas dataset. Pick a named scenario (e.g. ex07_investment_portfolio) and the skill fetches the right personas, builds SOUL.md for each agent, then runs the standard before/after flow.
argument-hint: "<scenario name or 'list' to see available scenarios>"
---

# Persona-Driven Before-and-After Consensus Testing

Same before-and-after methodology as the `before-and-after` skill, but agents are
built from **real, versioned personas** in the
[agent-personas](https://github.com/mycelium-io/agent-personas) dataset
instead of ad-hoc SOUL.md text.

Each agent's identity is composed from two YAML files:
- **preference** — who the agent is, what they want, their red lines and concession order
- **strategy** — the negotiation protocol injected verbatim into their system prompt
  (time-pressure handling, counter-offer rules, JSON reply format)

**You are the test harness.** Fetch personas, build agents, seed scenarios, observe
transcripts, evaluate.

---

## Phase 0: Prerequisites Check

Before anything else, verify the stack. Run each check and stop if any fail.

```bash
# 1. Mycelium CLI
mycelium --version

# 2. Resolve backend URL — NEVER hardcode a port
MYCELIUM_API_URL=$(python3 -c "
import toml, os
cfg = toml.load(os.path.expanduser('~/.mycelium/config.toml'))
print(cfg.get('server', {}).get('api_url', 'http://localhost:8000'))
")
echo "Backend: $MYCELIUM_API_URL"

# 3. Stack health
curl -sf "$MYCELIUM_API_URL/health" | python3 -m json.tool

# 4. OpenClaw
openclaw --version

# 4b. Mycelium health check
mycelium doctor
# All checks should be green. Fix any errors before proceeding.

# 5. OpenClaw gateway
openclaw channels status

# 6. git (required to fetch the persona dataset at runtime)
git --version

# 7. Mycelium repo path (for the bundled plugin source)
MYCELIUM_REPO=$(pwd)  # assumes running from the mycelium repo
ls "$MYCELIUM_REPO/mycelium-cli/src/mycelium/integrations/openclaw/assets/mycelium/plugin/index.ts" 2>/dev/null \
  && echo "Repo found: $MYCELIUM_REPO" \
  || echo "ERROR: not in the mycelium repo — cd to it first"
```

If any prerequisite fails, fix it before proceeding.

**Throughout this skill, use `$MYCELIUM_API_URL` for all backend requests. Never hardcode a port.**

---

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
    MAS_ID=$(curl -sf "$MYCELIUM_API_URL/api/rooms/$ACTIVE_ROOM" | python3 -c "
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


---

## Phase 0.5: Choose Persona Source

Use `AskUserQuestion` to ask:

> **How should agent personas be built?**
> 1. **From the `agent-personas` dataset** *(recommended — versioned scenarios with rich preference + strategy files; fetched automatically from `github.com/mycelium-io/agent-personas`)*
> 2. **Inline** — describe each agent yourself; the skill writes SOUL.md from your description. Before/after difference comes from the Mycelium protocol alone (no strategy injection).

Set `PERSONA_SOURCE` based on the answer:

```bash
PERSONA_SOURCE="dataset"   # Option 1
# or
PERSONA_SOURCE="inline"    # Option 2
```

---

### Option 1: Fetch the Persona Dataset

Skip to **Phase 0.6** if `PERSONA_SOURCE=dataset`. Otherwise skip ahead to **Phase 0.55**.

Clone the persona dataset into a temp directory. This is the single source of
truth — **do not hardcode persona text inline**. Always read from these files.

```bash
PERSONAS_DIR=$(mktemp -d)
git clone --depth 1 https://github.com/mycelium-io/agent-personas.git "$PERSONAS_DIR"
echo "Personas cloned to: $PERSONAS_DIR"
ls "$PERSONAS_DIR/profiles/"
```

The layout is:
```
$PERSONAS_DIR/
  preferences/     — domain identity + concession priorities (<name>.yaml, key: domain)
  strategies/      — negotiation protocol (<name>.yaml, key: negotiate or general)
  profiles/
    default/       — 3 generic domain-archetype agents (agent_a, agent_b, agent_c)
    ex01_*/        — mission-specific agent profiles
    ex0N_*/          each profile is a tiny YAML with persona_parts: [preference, strategy]
```

---

## Phase 0.55: Inline Persona Collection (skip if `PERSONA_SOURCE=dataset`)

Ask the user how many agents they want (default: 2), then for each agent collect:
- A name/handle (e.g. `agent-a`, `frontend-lead`)
- A persona description: who they are, what they value, their position, any red lines

Good descriptions include concrete experience and data points:
> "Backend architect, 10 years of REST APIs, believes GraphQL adds unnecessary complexity. Has data showing 60% faster onboarding with OpenAPI tooling. Won't compromise on cacheability."

For each agent, write **identical** content to both the before and after JSON — the before/after contrast will come purely from the Mycelium protocol, not persona strategy injection.

```python
python3 << 'PYEOF'
import json, os

# Replace these with the agent names and descriptions collected above
agents_inline = {
    "agent-a": "< description from user >",
    "agent-b": "< description from user >",
    # add more as needed
}

with open("/tmp/exp_personas_before.json", "w") as f:
    json.dump(agents_inline, f, indent=2)
with open("/tmp/exp_personas_after.json", "w") as f:
    json.dump(agents_inline, f, indent=2)

print(f"Wrote {len(agents_inline)} inline personas (identical before/after)")
for name, soul in agents_inline.items():
    print(f"  {name}: {len(soul)} chars")
PYEOF
```

Also set the scenario prompt from the user's description of the decision to be made:

```bash
SCENARIO_PROMPT="<what are the agents deciding? derive from the user's input>"
export SCENARIO_PROMPT
```

Then **skip directly to Phase 0.8** — Phases 0.6, 0.65, and 0.7 are dataset-only.

---

## Phase 0.6: Choose a Scenario / List Available Ones

If the user passed `list` as the argument, print available scenarios and stop:

```bash
echo "Available scenarios:"
ls "$PERSONAS_DIR/profiles/"
echo ""
echo "Usage: run this skill with one of the above scenario names as the argument."
echo "Example: persona-before-and-after ex07_investment_portfolio"
echo ""
echo "To run a mission from missions.yaml on a profile:"
echo "  persona-before-and-after default --mission \"Hard 01 - AI Model Deployment Policy\""
```

Otherwise, parse the scenario and optional `--mission` flag from the argument:

```bash
# Parse: <scenario> [--mission "<mission name>"]
# Examples:
#   ex07_investment_portfolio
#   default --mission "Hard 01 - AI Model Deployment Policy"
SCENARIO="default"        # replace with the first token of the user's argument
MISSION_NAME=""           # replace with the value after --mission, or leave empty

PROFILES_DIR="$PERSONAS_DIR/profiles/$SCENARIO"

# Verify the profile exists
ls "$PROFILES_DIR" || { echo "ERROR: scenario '$SCENARIO' not found. Run with 'list' to see options."; exit 1; }

echo "Agents in this scenario:"
for f in "$PROFILES_DIR"/*.yaml; do basename "$f" .yaml; done

echo "Mission: ${MISSION_NAME:-(derived from agent domains)}"
```

---

## Phase 0.65: Load Mission from missions.yaml (when --mission is set)

Skip this phase if `MISSION_NAME` is empty — the prompt will be derived from agent
domains in Phase 2a as usual.

When `MISSION_NAME` is set, read `missions.yaml` and extract `content_text` and
`n_steps` for the named mission. These override the Phase 2a prompt derivation and
the Phase 2c cost-guard threshold.

```python
python3 << 'PYEOF'
import yaml, os, sys

mission_name = os.environ.get("MISSION_NAME", "").strip()
if not mission_name:
    print("No --mission specified — skipping Phase 0.65")
    sys.exit(0)

personas_dir = os.environ["PERSONAS_DIR"]
missions_path = os.path.join(personas_dir, "missions.yaml")

with open(missions_path) as f:
    data = yaml.safe_load(f)

missions = data.get("missions", [])
match = next((m for m in missions if m["name"] == mission_name), None)
if not match:
    available = [m["name"] for m in missions]
    print(f"ERROR: mission '{mission_name}' not found in missions.yaml.")
    print("Available missions:")
    for n in available:
        print(f"  - {n}")
    sys.exit(1)

content_text = match["content_text"].strip()
n_steps = match.get("n_steps", 30)

# Write to a temp file for subsequent phases to source
with open("/tmp/exp_mission.env", "w") as f:
    # shell-safe: single-quote the prompt, escaping any embedded single quotes
    safe_prompt = content_text.replace("'", "'\\''")
    f.write(f"SCENARIO_PROMPT='{safe_prompt}'\n")
    f.write(f"COST_GUARD_STEPS={n_steps}\n")

print(f"Mission loaded: '{mission_name}'")
print(f"n_steps: {n_steps}")
print(f"content_text preview: {content_text[:200]}{'...' if len(content_text) > 200 else ''}")
PYEOF
```

```bash
export PERSONAS_DIR MISSION_NAME
python3 << 'PYEOF'
# ... (script above)
PYEOF

# Source the extracted values if the mission file was written
if [ -f /tmp/exp_mission.env ]; then
    source /tmp/exp_mission.env
    export SCENARIO_PROMPT COST_GUARD_STEPS
    echo "SCENARIO_PROMPT and COST_GUARD_STEPS loaded from mission."
fi
```

---

## Phase 0.7: Compose Agent Personas

For each profile YAML in the scenario, resolve `persona_parts` and produce **two
separate persona sets**:

- **before** — preference parts only (no strategy/negotiate blocks). Agents know who
  they are and what they want, but have no knowledge of the Mycelium CLI protocol.
  This is the control: uncontaminated by structured-negotiation instructions.
- **after** — full persona (preference + strategy). Agents carry the complete
  negotiation protocol, including the CLI command format and convergence rules.

```python
python3 << 'PYEOF'
import yaml, os, sys, json

personas_dir = os.environ["PERSONAS_DIR"]
scenario     = os.environ["SCENARIO"]
profiles_dir = os.path.join(personas_dir, "profiles", scenario)

# Keys whose file content is a negotiation/strategy protocol (not identity)
STRATEGY_KEYS = {"negotiate", "general"}

agents_before = {}  # preference-only
agents_after  = {}  # preference + strategy

for profile_file in sorted(os.listdir(profiles_dir)):
    if not profile_file.endswith(".yaml"):
        continue
    agent_name = profile_file.replace(".yaml", "")
    with open(os.path.join(profiles_dir, profile_file)) as f:
        profile = yaml.safe_load(f)

    pref_parts     = []
    strategy_parts = []

    for part_path in profile.get("persona_parts", []):
        # part_path is relative to $PERSONAS_DIR, e.g. "personas/preferences/ex07_risk_agent.yaml"
        # strip leading "personas/" since we cloned the repo root (which IS the personas dir)
        rel = part_path.replace("personas/", "", 1)
        abs_path = os.path.join(personas_dir, rel)
        with open(abs_path) as pf:
            data = yaml.safe_load(pf)
        # each file has exactly one key (domain, negotiate, general) — extract its value
        for key, value in data.items():
            if key in STRATEGY_KEYS:
                strategy_parts.append(value.strip())
            else:
                pref_parts.append(value.strip())

    soul_before = "\n\n".join(pref_parts)
    soul_after  = "\n\n".join(pref_parts + strategy_parts)

    agents_before[agent_name] = soul_before
    agents_after[agent_name]  = soul_after

    print(f"--- {agent_name} ---")
    print(f"  before: {len(soul_before)} chars (preference only)")
    print(f"  after:  {len(soul_after)} chars (preference + strategy)")
    print()

with open("/tmp/exp_personas_before.json", "w") as f:
    json.dump(agents_before, f, indent=2)
with open("/tmp/exp_personas_after.json", "w") as f:
    json.dump(agents_after, f, indent=2)

print(f"Composed {len(agents_before)} agent personas")
print("  /tmp/exp_personas_before.json — preference-only (for before case)")
print("  /tmp/exp_personas_after.json  — full persona    (for after case)")
PYEOF
```

Export the variables so the inline python3 can see them:

```bash
export PERSONAS_DIR SCENARIO
python3 << 'PYEOF'
# ... (script above)
PYEOF
```

Verify the output: the `before` soul should contain only the identity/domain block.
The `after` soul should append the `negotiate:` protocol block. If strategy parts are
missing from the after set, the profile's `persona_parts` only references preference
files — check the profile YAML.

## Phase 0.8: Choose Experiment LLM & API Key

Each scenario fires 10–40+ LLM calls. **Default to haiku** unless the user explicitly
wants sonnet.

First, check what model is already configured in openclaw:

```bash
CONFIGURED_MODEL=$(python3 -c "
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
try:
    cfg = json.load(open(p))
    print(cfg.get('agents', {}).get('defaults', {}).get('model', ''))
except Exception:
    print('')
")
echo "Currently configured model: ${CONFIGURED_MODEL:-'(none)'}"
```

Use `AskUserQuestion` — **include the currently configured model as an option if one is set**:

> **Which LLM should the experiment agents use?**
> 1. **Haiku** *(recommended — ~$0.10–0.30 per full experiment)*
> 2. **Sonnet** *(~$1.50–4.00 per full experiment)*
> 3. **Currently configured model** (`$CONFIGURED_MODEL`) *(reuse existing openclaw default — no setup needed)* ← only show if `$CONFIGURED_MODEL` is non-empty
> 4. **Different API key or provider** *(isolate experiment cost to a separate key)*

If the configured model is already haiku or sonnet, collapse options 1/2 and 3 into one.

```bash
# Option 1
EXP_MODEL="litellm/bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"

# Option 2
EXP_MODEL="litellm/bedrock/global.anthropic.claude-sonnet-4-6"

# Option 3 — reuse already-configured openclaw model
EXP_MODEL="$CONFIGURED_MODEL"

# Option 4 — ask for provider+model string and API key; export key in shell only
EXP_MODEL="<provider/model from user>"
export ANTHROPIC_API_KEY="sk-ant-..."   # or equivalent; ephemeral, not written to openclaw.json
```

**Never hardcode a model.** Always use `$EXP_MODEL`.

```bash
echo "Using model: $EXP_MODEL (key: $([ -n "${EXP_ANTHROPIC_KEY:-}" ] && echo 'experiment-scoped' || echo 'openclaw default'))"
```

---

## Phase 1: Setup

### 1a. Create Temporary Experiment Agents

```bash
EXP_ID="exp-$(date +%s | tail -c 5)"
echo "Experiment ID: $EXP_ID"
```

Read the agent list from the composed personas:

```bash
AGENT_NAMES=$(python3 -c "import json; d=json.load(open('/tmp/exp_personas_before.json')); print(' '.join(d.keys()))")
echo "Agents: $AGENT_NAMES"
```

Create one OpenClaw agent per persona:

```bash
for AGENT_NAME in $AGENT_NAMES; do
  EXP_AGENT="${EXP_ID}-${AGENT_NAME}"
  openclaw agents add "$EXP_AGENT" \
    --non-interactive \
    --workspace ~/.openclaw/workspaces/${EXP_AGENT} \
    --model "$EXP_MODEL"
  echo "Created: $EXP_AGENT"
done
```

Disable sandbox for all experiment agents (without this, agents can't run the
`mycelium` CLI in the after case):

```bash
python3 -c "
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
for a in cfg['agents']['list']:
    if a.get('id', '').startswith('${EXP_ID}-'):
        a['sandbox'] = {'mode': 'off'}
        print(f\"{a['id']} → sandbox: off\")
json.dump(cfg, open(p, 'w'), indent=2)
"
```

### 1b. Write Persona SOUL.md Files (before-case: preference-only)

Write the **preference-only** personas for the before case. Agents will know their
identity, red lines, and goals — but will have no knowledge of the Mycelium CLI
protocol. This prevents contamination of the control case.

```python
python3 << 'PYEOF'
import json, os

exp_id = os.environ["EXP_ID"]
agents = json.load(open("/tmp/exp_personas_before.json"))

for agent_name, soul_text in agents.items():
    exp_agent = f"{exp_id}-{agent_name}"
    workspace = os.path.expanduser(f"~/.openclaw/workspaces/{exp_agent}")
    os.makedirs(workspace, exist_ok=True)
    soul_path = os.path.join(workspace, "SOUL.md")
    with open(soul_path, "w") as f:
        f.write(soul_text + "\n")
    print(f"Wrote SOUL.md for {exp_agent} ({len(soul_text)} chars, preference-only)")
PYEOF
```

```bash
export EXP_ID
python3 << 'PYEOF'
# ... (script above)
PYEOF
```

The SOUL.md at this point contains **only** the identity/domain block — who the agent
is, their position, red lines, and concession order. The strategy/negotiate block is
intentionally absent. It will be written in Phase 3a before the after case runs.

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

### 1d. Install the Mycelium Plugin

```bash
ls ~/.openclaw/extensions/mycelium/openclaw.plugin.json 2>/dev/null \
  && echo "Mycelium plugin already installed" \
  || { echo "Installing..."; mycelium adapter add openclaw; }
```

If newly installed:

```bash
openclaw gateway restart
```

### 1e. Configure openclaw.json

Build the agent list and configure the channel:

```python
python3 << 'PYEOF'
import json, os, toml

mycelium_cfg = toml.load(os.path.expanduser("~/.mycelium/config.toml"))
backend_url  = mycelium_cfg.get("server", {}).get("api_url", "http://localhost:8000")

exp_id    = os.environ["EXP_ID"]
room_name = os.environ.get("EXP_ROOM", f"{exp_id}-before")

personas   = json.load(open("/tmp/exp_personas_before.json"))
exp_agents = [f"{exp_id}-{name}" for name in personas.keys()]

oc_path = os.path.expanduser("~/.openclaw/openclaw.json")
with open(oc_path) as f:
    oc = json.load(f)

oc.setdefault("plugins", {}).setdefault("entries", {})["mycelium-channel"] = {"enabled": True}
allow = oc["plugins"].setdefault("allow", [])
if "mycelium-channel" not in allow:
    allow.append("mycelium-channel")
ext_path = os.path.expanduser("~/.openclaw/extensions/mycelium-channel")
load_paths = oc["plugins"].setdefault("load", {}).setdefault("paths", [])
if ext_path not in load_paths:
    load_paths.append(ext_path)

oc.setdefault("channels", {})["mycelium-room"] = {
    "enabled": True,
    "backendUrl": backend_url,
    "room": room_name,
    "agents": exp_agents,
    "requireMention": True,
}

with open(oc_path, "w") as f:
    json.dump(oc, f, indent=2)

print(f"Config updated: room={room_name}, agents={exp_agents}, backend={backend_url}")
PYEOF
```

```bash
export EXP_ID EXP_ROOM="${EXP_ID}-before"
python3 << 'PYEOF'
# ... (script above)
PYEOF
```

### 1f. Create Experiment Rooms

```bash
mycelium room create "${EXP_ID}-before"
mycelium room create "${EXP_ID}-after"
```

### 1f. Restart Gateway and Verify

```bash
openclaw gateway restart
sleep 3
grep "mycelium-room.*SSE connected" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -1
```

---

## Phase 2: Run "Before" (Unstructured Channel)

### 2a. Build the Scenario Prompt

If `SCENARIO_PROMPT` is already set (loaded from `missions.yaml` in Phase 0.65),
skip this step — it is ready to use.

Otherwise, derive it from the agent domain blocks:

```bash
if [ -n "$SCENARIO_PROMPT" ]; then
    echo "Using mission prompt (Phase 0.65): ${SCENARIO_PROMPT:0:120}..."
else
    # Derive from agent identity blocks
    python3 -c "
import json
agents = json.load(open('/tmp/exp_personas_before.json'))
for name, soul in agents.items():
    print(f'=== {name} ===')
    print(soul.split('\n\n')[0][:300])
    print()
"
    # Set the prompt based on what the agents are fighting over:
    SCENARIO_PROMPT="<derive from the agent domains above — what decision do they need to reach?>"
    export SCENARIO_PROMPT
fi
```

### 2b. Seed the Conversation

The seed must @-mention every agent (channel is `requireMention: true`) and tell them
to @-mention each other to continue:

```bash
AGENT_NAMES=$(python3 -c "import json; d=json.load(open('/tmp/exp_personas_before.json')); print(' '.join(d.keys()))")
MENTIONS=$(for n in $AGENT_NAMES; do printf "@${EXP_ID}-${n} "; done)

SEED_BODY="${MENTIONS}

${SCENARIO_PROMPT}

How to work together in this room:
- Reply by @-mentioning the other agent(s) whenever you want them to respond.
  Messages without an @mention are ignored.
- Keep each message to 2–3 paragraphs.
- Aim for consensus. When you agree, @-mention the others and say 'I agree' with
  the final decision explicitly stated.

IMPORTANT: This is a plain-text chat room. Do NOT use any CLI tools, shell
commands, or negotiation protocols. Do NOT reference CognitiveEngine, mycelium
session join, or any structured negotiation framework. Respond only in plain
conversational text."

curl -sf "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-before/messages" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,sys; print(json.dumps({'sender_handle':'facilitator','message_type':'broadcast','content':sys.argv[1]}))" "$SEED_BODY")"
```

### 2c. Monitor and Wait for Convergence

```bash
grep "mycelium-room.*←\|mycelium-room.*→" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -20
```

Poll room messages:

```bash
curl -sf "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-before/messages?limit=20" | python3 -c "
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

**Cost guard:** Cut the before case if you see ≥3 distinct "consensus" messages with
different substance, scope creep re-opening settled items, or >${COST_GUARD_STEPS:-30}
messages without unanimous agreement (`n_steps` from `missions.yaml` when a mission is
loaded, otherwise 30). To kill it cleanly:

```bash
python3 -c "
import json, os
p = os.path.expanduser('~/.openclaw/openclaw.json')
cfg = json.load(open(p))
cfg['channels']['mycelium-room']['room'] = '${EXP_ID}-after'
json.dump(cfg, open(p, 'w'), indent=2)
"
openclaw gateway restart
```

### 2d. Capture Transcript

```bash
curl -sf "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-before/messages?limit=50" | python3 -c "
import sys, json
data = json.load(sys.stdin)
msgs = data.get('messages', data) if isinstance(data, dict) else data
if isinstance(msgs, list):
    msgs.reverse()
    for m in msgs:
        print(f'**{m[\"sender_handle\"]}:**')
        print(m['content'])
        print()
" > ~/.mycelium/rooms/${EXP_ID}-before/transcript.md
```

### 2e. Capture CFN Ingest Log for the Before Window

Every time the `mycelium-knowledge-extract` hook fires during the before run
it appends an event to the in-memory buffer on mycelium-backend. Capture the
full buffer to disk so the experiment artifact has a per-event cost trail.

```bash
mycelium cfn log --limit 500 --json > ~/.mycelium/rooms/${EXP_ID}-before/ingest-log.json
mycelium cfn stats --json > ~/.mycelium/rooms/${EXP_ID}-before/ingest-stats.json
```

For human review during the run, `mycelium cfn log --state=refused,error` is
the fast signal on “did anything blow up here.”

---

## Phase 3: Run "After" (Mycelium Structured Negotiation)

### 3a. Rewrite SOUL.md with full personas, re-enable bootstrap hook, switch to after room

Three things happen here in order:

1. **Rewrite SOUL.md** — swap the preference-only SOUL.md for the full persona
   (preference + strategy). Agents now carry the Mycelium CLI negotiation protocol.
2. **Re-enable bootstrap hook** (if it was disabled) — agents get `MYCELIUM_ROOM_ID`
   injected at bootstrap.
3. **Switch channel to the after room** and restart the gateway.

```python
# Step 1: rewrite SOUL.md files with full (preference + strategy) personas
python3 << 'PYEOF'
import json, os

exp_id = os.environ["EXP_ID"]
agents = json.load(open("/tmp/exp_personas_after.json"))

for agent_name, soul_text in agents.items():
    exp_agent = f"{exp_id}-{agent_name}"
    soul_path = os.path.expanduser(f"~/.openclaw/workspaces/{exp_agent}/SOUL.md")
    with open(soul_path, "w") as f:
        f.write(soul_text + "\n")
    print(f"Rewrote SOUL.md for {exp_agent} ({len(soul_text)} chars, preference + strategy)")
PYEOF
```

```bash
export EXP_ID
python3 << 'PYEOF'
# ... (script above)
PYEOF
```

```bash
# Step 2: re-enable bootstrap hook — agents now get MYCELIUM_ROOM_ID injected
openclaw hooks enable mycelium-bootstrap

# Step 3: switch channel to after room
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

### 3b. Seed with Negotiation Instructions

The agents now have the negotiation protocol in their SOUL.md (just written in 3a).
The seed activates it — tell them to use `mycelium session join` and the CLI protocol
rather than chatting:

```bash
MENTIONS=$(for n in $AGENT_NAMES; do printf "@${EXP_ID}-${n} "; done)

SEED_BODY="${MENTIONS}

${SCENARIO_PROMPT}

Use Mycelium structured negotiation. Do NOT discuss in chat — run CLI commands instead:

1. Each of you joins the session once with your own handle:
     mycelium session join --handle <your-handle> --room ${EXP_ID}-after -m \"<your opening position>\"

2. Wait for the CognitiveEngine tick. It will tell you the current offer and
   whether to 'propose' or 'respond'.

3. Respond via CLI (your SOUL.md has the exact JSON format):
     mycelium negotiate propose ISSUE=VALUE ISSUE=VALUE ... --room ${EXP_ID}-after --handle <your-handle>
     mycelium negotiate respond accept --room ${EXP_ID}-after --handle <your-handle>
     mycelium negotiate respond reject --room ${EXP_ID}-after --handle <your-handle>

Briefly explain your reasoning in chat before each CLI command (1–2 sentences max).
Your SOUL.md already contains the full negotiation protocol — follow it.

IMPORTANT: Never declare consensus yourself in chat. Only CognitiveEngine can
confirm consensus. Keep responding to ticks until one of two things happens:
- CognitiveEngine sends a 'consensus' message → negotiation is complete.
- CognitiveEngine sends a 'timeout' or broken=true message → rounds exhausted
  without agreement. In that case, post one final message stating the last
  position you accepted (if any), so the transcript has a readable final state."

curl -sf "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-after/messages" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,sys; print(json.dumps({'sender_handle':'facilitator','message_type':'broadcast','content':sys.argv[1]}))" "$SEED_BODY")"
```

### 3c. Monitor

```bash
# Ticks and consensus
grep "mycelium-room.*🎯\|mycelium-room.*🤝" /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | tail -20

# Session state
curl -sf "$MYCELIUM_API_URL/api/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '${EXP_ID}-after' in r['name']:
        print(f'{r[\"name\"]}: {r.get(\"coordination_state\", \"none\")}')
"
```

### 3d. Capture Transcript

```bash
# Main room
curl -sf "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-after/messages?limit=50" | python3 -c "
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

# Session sub-room (ticks, proposals, consensus records)
SESSION_ROOM=$(curl -sf "$MYCELIUM_API_URL/api/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '${EXP_ID}-after:session:' in r['name']:
        print(r['name']); break
")
echo "Session room: $SESSION_ROOM"
curl -sf "$MYCELIUM_API_URL/api/rooms/$SESSION_ROOM/messages?limit=100" | python3 -c "
import sys, json
data = json.load(sys.stdin)
msgs = data.get('messages', data) if isinstance(data, dict) else data
if isinstance(msgs, list):
    msgs.reverse()
    for m in msgs:
        raw = m['content']
        c = (json.dumps(raw) if isinstance(raw, (dict, list)) else str(raw))[:200]
        print(f'[{m[\"message_type\"]}] {m.get(\"sender_handle\",\"\")}: {c}')
        print()
" > ~/.mycelium/rooms/${EXP_ID}-after/session-transcript.md
```

### 3e. Capture CFN Ingest Log for the After Window

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

---

## Phase 4: Evaluate

Compare transcripts. Score each criterion 1–5:

| Score | Meaning |
|-------|---------|
| 1 | Not addressed |
| 2 | Mentioned, unresolved |
| 3 | Partially addressed |
| 4 | Substantially addressed |
| 5 | Fully resolved |

Before writing the report, count messages for both cases:

```bash
python3 - <<'PY'
import pathlib, os, re
exp = os.environ["EXP_ID"]
base = pathlib.Path("~/.mycelium/rooms").expanduser()

def count_room_msgs(label):
    p = base / f"{exp}-{label}" / "transcript.md"
    if not p.exists():
        return "missing"
    # Count lines that are sender headers: start with ** and end with **:
    return sum(1 for l in p.read_text().splitlines()
               if l.startswith("**") and l.rstrip().endswith(":**"))

def count_session_msgs(transcript):
    # Count by message type from [type] prefix lines
    counts = {}
    for l in transcript.splitlines():
        m = re.match(r'^\[([^\]]+)\]', l)
        if m:
            t = m.group(1)
            counts[t] = counts.get(t, 0) + 1
    return counts

before_chat = count_room_msgs("before")
after_chat  = count_room_msgs("after")
print(f"before — room chat messages (= negotiation moves): {before_chat}")
print(f"after  — room chat messages (narration only):      {after_chat}")

sess_path = base / f"{exp}-after" / "session-transcript.md"
if sess_path.exists():
    sc = count_session_msgs(sess_path.read_text())
    direct = sc.get("direct", 0)
    ticks  = sc.get("coordination_tick", 0)
    joins  = sc.get("coordination_join", 0)
    rounds = ticks // max(sc.get("coordination_join", 1), 1)  # ticks / n_agents
    print(f"after  — session direct responses (= negotiation moves): {direct}")
    print(f"after  — CE ticks (protocol overhead): {ticks}  joins: {joins}")
    print(f"after  — rounds (ticks / n_agents): {ticks // joins if joins else '?'}")
PY
```

**What these numbers mean for the Summary table:**
- `before room chat messages` ≈ negotiation moves (every chat turn is a decision)
- `after session direct responses` = negotiation moves (the JSON accept/reject/counter-offer actions)
- `after room chat messages` = narration overhead only — agents explain reasoning before running CLI
- CE ticks are protocol infrastructure, not comparable to anything in the before case

Use `before room chat` vs `after session direct` as the apples-to-apples move count.
Use `after room chat` as a separate "narration overhead" metric if desired.

Write the report to `~/.mycelium/rooms/${EXP_ID}/evaluation.md`:

```markdown
## Persona Before-and-After: {scenario} — {EXP_ID}

### Persona Set
| Agent | Preference File | Strategy File |
|-------|----------------|---------------|
| ... | ... | ... |

### Summary
| Metric | Before (Channel) | After (Mycelium) |
|--------|-----------------|-----------------|
| Consensus reached? | ... | ... |
| Negotiation moves | {before room msgs} | {after session direct responses} |
| Chat/reasoning messages | {before room msgs} | {after room msgs} |
| CE protocol overhead | n/a | {ticks} ticks / {rounds} rounds |
| Issues explicitly identified | ... | ... |
| Issues resolved | ... | ... |
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
- What worked:
- What failed:
- Did persona identity survive unstructured chat? (did agents stay in character?)

**After (Mycelium-mediated):**
- What worked:
- What failed:
- Did the strategy protocol (JSON counter-offers, convergence rules) produce better outcomes?

### Verdict
{honest assessment — include whether persona richness made a difference}
```

---

## Phase 4b: (Optional) Share Results as a Gist

Experiment artifacts are often worth sharing with teammates. Inline posting hits
GitHub's 65,536-char comment limit fast; gists are the cleanest path.

**Before creating a gist, scan for secrets.** Agent narration can leak absolute home
paths, API keys from shell env, or session tokens:

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

The ingest-log JSON files are particularly worth scanning — they include
the full payload content that was forwarded to CFN, which for agent turns
may include filesystem paths, shell output, or tool results. Err on the
side of redacting.
```

If anything lights up, redact or skip the gist. **Always ask the user before uploading.**

Also fetch the knowledge graph and run semantic queries — this is the most interesting
artifact to show teammates:

```bash
# Get the MAS ID from config
MAS=$(python3 -c "
import toml, os
cfg = toml.load(os.path.expanduser('~/.mycelium/config.toml'))
print(cfg['server']['mas_id'])
")

# Dump all nodes grouped by type
mycelium cfn ls --mas "$MAS" --limit 500 --json 2>/dev/null | python3 -c "
import sys, json
nodes = json.load(sys.stdin).get('nodes', [])
print(f'## Knowledge Graph ({len(nodes)} nodes)\\n')
by_type = {}
for n in nodes:
    t = n.get('node_type', 'unknown')
    by_type.setdefault(t, []).append(n)
for t, ns in sorted(by_type.items(), key=lambda x: -len(x[1])):
    print(f'### {t} ({len(ns)})')
    for n in ns[:20]:
        label = n.get('label') or n.get('name') or n.get('id', '')[:12]
        desc = (n.get('description') or n.get('summary') or '')[:100]
        print(f'- **{label}**: {desc}')
    if len(ns) > 20:
        print(f'  ... and {len(ns)-20} more')
    print()
" > /tmp/cfn-knowledge-graph.md

# Run 2-3 semantic queries relevant to the scenario
mycelium cfn query "What were the key decisions and agreements reached?" \
  --mas "$MAS" > /tmp/cfn-query-decisions.txt 2>&1

mycelium cfn query "What were the main points of disagreement and how were they resolved?" \
  --mas "$MAS" > /tmp/cfn-query-disagreements.txt 2>&1

echo "Knowledge graph: $(wc -l < /tmp/cfn-knowledge-graph.md) lines"
echo "Query results written"
```

Stage everything under unique names to avoid filename collisions, then push as a gist:

```bash
STAGE=$(mktemp -d)
EVAL_DIR=~/.mycelium/rooms/${EXP_ID}
cp "$EVAL_DIR/evaluation.md" "$STAGE/evaluation.md"
# Transcripts — prefer copies in eval dir (written by Phase 5), fall back to live room dirs
for label in before after; do
  for fname in transcript.md session-transcript.md ingest-log.json ingest-stats.json; do
    src_eval="$EVAL_DIR/${label}-${fname}"
    src_room=~/.mycelium/rooms/${EXP_ID}-${label}/${fname}
    dest="$STAGE/${label}-${fname}"
    if [ -f "$src_eval" ]; then
      cp "$src_eval" "$dest"
    elif [ -f "$src_room" ]; then
      cp "$src_room" "$dest"
    fi
  done
done
# Knowledge graph artifacts
cp /tmp/cfn-knowledge-graph.md       "$STAGE/cfn-knowledge-graph.md" 2>/dev/null || true
cp /tmp/cfn-query-decisions.txt      "$STAGE/cfn-query-decisions.txt" 2>/dev/null || true
cp /tmp/cfn-query-disagreements.txt  "$STAGE/cfn-query-disagreements.txt" 2>/dev/null || true

# Upload via API (no gh CLI required)
GIST_PAYLOAD=$(python3 -c "
import json, os, sys
stage = sys.argv[1]
files = {}
for fname in sorted(os.listdir(stage)):
    with open(os.path.join(stage, fname)) as f:
        files[fname] = {'content': f.read()}
print(json.dumps({'description': '${EXP_ID}: ${SCENARIO} — persona before-and-after', 'public': False, 'files': files}))
" "$STAGE")

curl -sf -X POST https://api.github.com/gists \
  -H "Authorization: token <PAT>" \
  -H "Content-Type: application/json" \
  -d "$GIST_PAYLOAD" | python3 -c "import sys,json; print(json.load(sys.stdin).get('html_url',''))"
```

Notes:
- Pass `"public": true` in the payload only if the user explicitly asks.
- The gist URL is permanent; link to it from PR comments or issue comments.
- GitHub does not support file attachments via API for PR/issue comments — gists are the closest scriptable alternative.
---

## Phase 5: Cleanup

```bash
# Remove experiment agents from openclaw config
python3 -c "
import json, os
oc_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(oc_path) as f:
    oc = json.load(f)
oc['agents']['list'] = [a for a in oc.get('agents',{}).get('list',[]) if not a.get('id','').startswith('${EXP_ID}')]
oc.get('channels', {}).pop('mycelium-room', None)
with open(oc_path, 'w') as f:
    json.dump(oc, f, indent=2)
print('Cleaned openclaw config')
"

# Remove workspaces
rm -rf ~/.openclaw/workspaces/${EXP_ID}-*
rm -rf ~/.openclaw/agents/${EXP_ID}-*

# Preserve transcripts into evaluation dir before deleting rooms
# (required by summarize_experiments.py for issue recall/F1 scoring)
mkdir -p ~/.mycelium/rooms/${EXP_ID}
for label in before after; do
  src=~/.mycelium/rooms/${EXP_ID}-${label}
  dst=~/.mycelium/rooms/${EXP_ID}
  [ -f "$src/transcript.md" ]         && cp "$src/transcript.md"         "$dst/${label}-transcript.md"
  [ -f "$src/session-transcript.md" ] && cp "$src/session-transcript.md" "$dst/${label}-session-transcript.md"
  [ -f "$src/ingest-log.json" ]       && cp "$src/ingest-log.json"       "$dst/${label}-ingest-log.json"
  [ -f "$src/ingest-stats.json" ]     && cp "$src/ingest-stats.json"     "$dst/${label}-ingest-stats.json"
done
echo "Transcripts preserved in ~/.mycelium/rooms/${EXP_ID}/"

# Delete rooms
mycelium room delete "${EXP_ID}-before" -f 2>/dev/null || curl -sf -X DELETE "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-before"
mycelium room delete "${EXP_ID}-after"  -f 2>/dev/null || curl -sf -X DELETE "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-after"

# Ensure hooks are back to their normal state
openclaw hooks enable mycelium-bootstrap
openclaw hooks enable mycelium-knowledge-extract

# Clean up temp dirs
rm -rf "$PERSONAS_DIR"
rm -f /tmp/exp_personas_before.json /tmp/exp_personas_after.json

openclaw gateway restart
```

---

## Input

Pass a scenario name as the argument. Available scenarios map to the `profiles/`
subdirectories in the [persona dataset](https://github.com/mycelium-io/agent-personas):

| Scenario | Agents | Domain |
|----------|--------|--------|
| `default` | agent_a, agent_b, agent_c | Generic domain archetypes (cost-conscious, quality-focused, pragmatic) |
| `ex01_email_automation` | archive, compliance, delete | Email triage policy |
| `ex02_inbox_thread_workflow` | bob, julie | Sequential vs parallel inbox workflow |
| `ex03_personal_planning` | family, fitness, work | Daily schedule time-slot allocation |
| `ex04_travel_planning` | flight, itinerary, stay | Italy trip: budget vs comfort vs sightseeing |
| `ex05_healthcare_treatment` | genomics, oncology, trial | Cancer treatment protocol |
| `ex06_expense_submission` | audit, compliance, expense | Expense submission vs validation gate |
| `ex07_investment_portfolio` | execution, growth, risk | Portfolio rebalancing: growth vs volatility |
| `ex08_supply_chain_stockout` | finance, logistics, procurement | Stockout resolution: cost vs speed vs supplier |
| `ex09_ci_cd_release` | deploy, qa, sre | CI/CD release: deadline vs test gates vs system health |

For a custom scenario not in this list, use the base `before-and-after` skill with
manually written personas, or add new preference/strategy/profile files to the
[persona dataset repo](https://github.com/mycelium-io/agent-personas) and
re-run this skill.

---

## Strategy Reference

The strategy file in each profile's `persona_parts` controls negotiation behaviour:

| Strategy | Time pressure | Convergence | Derailment | Best for |
|----------|--------------|-------------|------------|---------|
| `negotiate_v1_0` | ✅ tracks rounds | progressive locking | none | Most missions (default) |
| `negotiate_v1_1` | ❌ clock-agnostic | identical | none | Pure preference ablations |
| `negotiate_v1_2` | ✅ tracks rounds | identical | ~20% per round | Fault-injection / robustness testing |
| `negotiate_ov` | ✅ | primary-win / their-win | none | Single-issue extremist agents |

To test a different strategy, edit the profile YAML in the persona dataset and push.
The skill always does `--depth 1` clone so it gets the latest version automatically.

---

## Flags

- `list` — print available scenarios and exit
- `--before-only` — run only the unstructured case
- `--after-only` — run only the Mycelium negotiation case
- `--eval-only` — skip both runs, evaluate existing transcripts
- `--setup-only` — just configure agents and rooms, don't run experiments
- `--strategy negotiate_v1_2` — override the strategy for all agents in this run
  (useful for robustness testing without editing the profile files)

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| `git clone` of persona repo fails | No network / repo private | Check connectivity; ensure repo is public at github.com/mycelium-io/agent-personas |
| `yaml` module not found | PyYAML not installed | `pip install pyyaml` |
| Profile YAML has no `persona_parts` | Wrong file or typo | Check `ls $PERSONAS_DIR/profiles/$SCENARIO/` |
| Strategy block missing from after-case SOUL.md | Profile only refs a preference file | Add a strategy to `persona_parts` in the profile YAML; the before case intentionally omits it |
| `openclaw agents add` prompts interactively | Missing `--non-interactive` | Add `--non-interactive --workspace <path>` |
| `mycelium room create` returns 400 | Room name already exists | Use unique `$EXP_ID` prefix or delete existing room first |
| Agents don't respond in after case | Sandbox blocks `mycelium` CLI | Verify `sandbox: {mode: off}` was patched in Phase 1a, or `tools.exec.host = 'gateway'` set |
| After-case agents chat instead of using CLI | Strategy block not in SOUL.md | See above |
| `curl` to backend fails | Wrong port | Read from `~/.mycelium/config.toml` |
| No SSE connection | Plugin not loaded | Check plugin in `load.paths` and `allow` |
| Ticks never arrive (after case) | Session room SSE not subscribed | Check poll found session room; verify CFN is running (`docker logs mycelium-backend`) |
| Agent processes hang | `--local` flag or SSE loop in child | Ensure NOT using `--local`; check `MYCELIUM_CHANNEL_ONESHOT` env var |
| After-case agents say "mycelium CLI isn't available" | Experiment agents are sandboxed | Set `sandbox: {mode: "off"}` or `tools.exec.host = "gateway"` on each `exp-*` agent in `openclaw.json` and restart gateway. See Phase 1a. |


