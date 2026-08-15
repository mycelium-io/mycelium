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

Agents are **resident `claude_code` runtimes** — a live `claude` session per agent,
kept awake with `mycelium await --loop --exec claude`. The loop *is* the wake: each
agent long-polls its room, reasons on what it reads, and posts a reply with
`mycelium respond`. There is no gateway, no daemon, and no per-mention cold-spawn.

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

# 4. claude CLI (the resident agent runtime)
claude --version

# 4b. Mycelium health check
mycelium doctor
# All checks should be green. Fix any errors before proceeding.

# 5. git (required to fetch the persona dataset at runtime)
git --version

# 6. Mycelium repo path (for the bundled adapter source)
MYCELIUM_REPO=$(pwd)  # assumes running from the mycelium repo
ls "$MYCELIUM_REPO/mycelium-cli/src/mycelium/integrations/claude_code" 2>/dev/null \
  && echo "Repo found: $MYCELIUM_REPO" \
  || echo "ERROR: not in the mycelium repo — cd to it first"
```

If any prerequisite fails, fix it before proceeding.

**Throughout this skill, use `$MYCELIUM_API_URL` for all backend requests. Never hardcode a port.**

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

Check what model the resident `claude` sessions will use by default:

```bash
CONFIGURED_MODEL="${ANTHROPIC_MODEL:-}"
echo "Currently configured model: ${CONFIGURED_MODEL:-'(claude default)'}"
```

Use `AskUserQuestion` — **include the currently configured model as an option if one is set**:

> **Which LLM should the experiment agents use?**
> 1. **Haiku** *(recommended — ~$0.10–0.30 per full experiment)*
> 2. **Sonnet** *(~$1.50–4.00 per full experiment)*
> 3. **Currently configured model** (`$CONFIGURED_MODEL`) *(reuse the current `claude` default — no setup needed)* ← only show if `$CONFIGURED_MODEL` is non-empty
> 4. **Different API key or provider** *(isolate experiment cost to a separate key)*

If the configured model is already haiku or sonnet, collapse options 1/2 and 3 into one.

```bash
# Option 1
EXP_MODEL="claude-haiku-4-5"

# Option 2
EXP_MODEL="claude-sonnet-4-6"

# Option 3 — reuse the already-configured claude default
EXP_MODEL="$CONFIGURED_MODEL"

# Option 4 — ask for a model string and API key; export both in shell only
EXP_MODEL="<model from user>"
export ANTHROPIC_API_KEY="sk-ant-..."   # ephemeral; scoped to this shell only
```

**Never hardcode a model.** Always use `$EXP_MODEL`. The resident `claude` sessions
read it from `ANTHROPIC_MODEL`:

```bash
export ANTHROPIC_MODEL="$EXP_MODEL"
echo "Using model: $EXP_MODEL (key: $([ -n "${ANTHROPIC_API_KEY:-}" ] && echo 'experiment-scoped' || echo 'claude default'))"
```

---

## Phase 1: Setup

### 1a. Create Temporary Experiment Handles + Workspaces

```bash
EXP_ID="exp-$(date +%s | tail -c 5)"
echo "Experiment ID: $EXP_ID"
```

Read the agent list from the composed personas:

```bash
AGENT_NAMES=$(python3 -c "import json; d=json.load(open('/tmp/exp_personas_before.json')); print(' '.join(d.keys()))")
echo "Agents: $AGENT_NAMES"
```

Each persona runs as a resident `claude_code` agent out of its own workspace
directory. Create one workspace per persona:

```bash
for AGENT_NAME in $AGENT_NAMES; do
  EXP_AGENT="${EXP_ID}-${AGENT_NAME}"
  mkdir -p ~/.mycelium/experiments/${EXP_AGENT}
  echo "Created workspace: ~/.mycelium/experiments/${EXP_AGENT}"
done
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
    workspace = os.path.expanduser(f"~/.mycelium/experiments/{exp_agent}")
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

### 1c. Install the claude_code adapter

The adapter installs the Mycelium SKILL.md into each workspace so the resident
`claude` session knows the participation protocol (`await` → reason → `respond`).

```bash
mycelium adapter add claude_code 2>/dev/null \
  && echo "claude_code adapter installed" \
  || echo "claude_code adapter already present"
```

For the **before** case, we deliberately keep the Mycelium skill *out* of the
agents' path — the control must not know the protocol. We run before-case `claude`
sessions from a bare workspace with only SOUL.md, so nothing steers them toward the
CLI. The skill is only surfaced to the after-case workspaces in Phase 3a.

### 1d. Create Experiment Rooms

```bash
mycelium room create "${EXP_ID}-before"
mycelium room create "${EXP_ID}-after"
```

---

## Phase 2: Run "Before" (Unstructured Chat)

In the before case there is no aligner and no protocol. Each agent is a resident
`claude` session pointed at the before room; they converse by posting plain messages
and reading each other's replies. The contrast the experiment measures is: does
free-form chat reach a clean consensus on its own?

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

### 2b. Launch the Before-Case Agents

Start one resident `claude` loop per agent against the before room. Each loop
long-polls the room, reasons with its SOUL.md, and posts a plain reply. Run them in
the background so all agents are live at once:

```bash
AGENT_NAMES=$(python3 -c "import json; d=json.load(open('/tmp/exp_personas_before.json')); print(' '.join(d.keys()))")

for AGENT_NAME in $AGENT_NAMES; do
  EXP_AGENT="${EXP_ID}-${AGENT_NAME}"
  WORKSPACE=~/.mycelium/experiments/${EXP_AGENT}
  ( cd "$WORKSPACE" && \
    mycelium await --loop \
      --room "${EXP_ID}-before" \
      --handle "$EXP_AGENT" \
      --exec "claude --append-system-prompt \"\$(cat $WORKSPACE/SOUL.md)\"" \
    ) > "$WORKSPACE/before.log" 2>&1 &
  echo "Launched before-case agent: $EXP_AGENT (pid $!)"
done
```

### 2c. Seed the Conversation

The seed kicks off the discussion. It tells the agents to reply to each other in
plain text and to aim for consensus — and explicitly forbids the Mycelium CLI so the
control stays uncontaminated:

```bash
SEED_BODY="${SCENARIO_PROMPT}

How to work together in this room:
- Reply in plain conversational text; the other agents will read what you post.
- Keep each message to 2–3 paragraphs.
- Aim for consensus. When you agree, say 'I agree' with the final decision explicitly stated.

IMPORTANT: This is a plain-text chat room. Do NOT use any CLI tools, shell
commands, or negotiation protocols. Do NOT reference the aligner, mycelium
respond/await, or any structured negotiation framework. Respond only in plain
conversational text."

mycelium respond --room "${EXP_ID}-before" --handle facilitator "$SEED_BODY"
```

### 2d. Monitor and Wait for Convergence

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
loaded, otherwise 30). To kill it cleanly, stop the resident loops:

```bash
pkill -f "mycelium await --loop --room ${EXP_ID}-before" || true
```

### 2e. Capture Transcript

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

# Stop the before-case loops before moving on
pkill -f "mycelium await --loop --room ${EXP_ID}-before" || true
```

---

## Phase 3: Run "After" (Mycelium Structured Negotiation)

In the after case the personas carry the full negotiation protocol and coordination
runs through the **aligner** — a backend engine summoned by `@`-mention that runs a
real NEGMAS negotiation, `@`-addresses one agent at a time, owns termination, and
compiles the consensus into `plan/tasks.md`.

### 3a. Rewrite SOUL.md with full personas and install the skill

Two things happen here in order:

1. **Rewrite SOUL.md** — swap the preference-only SOUL.md for the full persona
   (preference + strategy). Agents now carry the Mycelium CLI negotiation protocol.
2. **Ensure the claude_code SKILL.md is present** in each after-case workspace so the
   resident session knows the `await` → reason → `respond` participation protocol.

```python
# Step 1: rewrite SOUL.md files with full (preference + strategy) personas
python3 << 'PYEOF'
import json, os

exp_id = os.environ["EXP_ID"]
agents = json.load(open("/tmp/exp_personas_after.json"))

for agent_name, soul_text in agents.items():
    exp_agent = f"{exp_id}-{agent_name}"
    soul_path = os.path.expanduser(f"~/.mycelium/experiments/{exp_agent}/SOUL.md")
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

# Step 2: install the claude_code SKILL.md into each after-case workspace
for AGENT_NAME in $AGENT_NAMES; do
  EXP_AGENT="${EXP_ID}-${AGENT_NAME}"
  mycelium adapter add claude_code --workspace ~/.mycelium/experiments/${EXP_AGENT} 2>/dev/null \
    && echo "skill installed for $EXP_AGENT" \
    || echo "skill already present for $EXP_AGENT"
done
```

### 3b. Register the aligner and launch the After-Case Agents

Register the aligner in the after room, then start a resident loop per agent. In the
after case the loop drives the full protocol: `await` the aligner's address → reason →
`respond`.

```bash
# Register the aligner once in the after room
mycelium engine create aligner --kind aligner --room "${EXP_ID}-after"

# Launch each agent as a resident that participates via the protocol
for AGENT_NAME in $AGENT_NAMES; do
  EXP_AGENT="${EXP_ID}-${AGENT_NAME}"
  WORKSPACE=~/.mycelium/experiments/${EXP_AGENT}
  ( cd "$WORKSPACE" && \
    mycelium await --loop \
      --room "${EXP_ID}-after" \
      --handle "$EXP_AGENT" \
      --exec "claude --append-system-prompt \"\$(cat $WORKSPACE/SOUL.md)\"" \
    ) > "$WORKSPACE/after.log" 2>&1 &
  echo "Launched after-case agent: $EXP_AGENT (pid $!)"
done
```

### 3c. Post Opening Positions and Summon the Aligner

Each agent posts an opening position, then summon the aligner to converge. The
aligner discovers issues from the opening positions and brokers the rounds:

```bash
# Each agent posts an opening position (the resident loops will pick up the
# aligner's addresses from here on). Derive each position from the persona.
for AGENT_NAME in $AGENT_NAMES; do
  EXP_AGENT="${EXP_ID}-${AGENT_NAME}"
  # Replace with a one-line opening position derived from the agent's SOUL.md
  mycelium respond --room "${EXP_ID}-after" --handle "$EXP_AGENT" "<opening position for $AGENT_NAME>"
done

# Summon the aligner to converge on the scenario
mycelium engine invoke aligner "$SCENARIO_PROMPT" -r "${EXP_ID}-after"
```

The aligner now `@`-addresses one agent at a time; each resident loop `await`s its
address, reasons with its SOUL.md strategy block, and posts a `respond`. NEGMAS owns
termination — it stops the instant the agents agree, then the plan compiler
materializes `plan/tasks.md` *before* consensus is announced.

### 3d. Monitor

```bash
# Room coordination state
curl -sf "$MYCELIUM_API_URL/api/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '${EXP_ID}-after' in r['name']:
        print(f'{r[\"name\"]}: {r.get(\"coordination_state\", \"none\")}')
"

# The compiled plan (exists once the aligner converges)
mycelium plan tasks --room "${EXP_ID}-after"
# Expect: a shared - [ ] checklist with @handle owners
```

### 3e. Capture Transcript

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

# Episode sub-room (aligner addresses, replies, consensus record)
EPISODE_ROOM=$(curl -sf "$MYCELIUM_API_URL/api/rooms" | python3 -c "
import sys, json
for r in json.load(sys.stdin):
    if '${EXP_ID}-after:episode:' in r['name']:
        print(r['name']); break
")
echo "Episode room: $EPISODE_ROOM"
if [ -n "$EPISODE_ROOM" ]; then
curl -sf "$MYCELIUM_API_URL/api/rooms/$EPISODE_ROOM/messages?limit=100" | python3 -c "
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
" > ~/.mycelium/rooms/${EXP_ID}-after/episode-transcript.md
fi

# Also capture the compiled plan as an artifact
mycelium plan tasks --room "${EXP_ID}-after" > ~/.mycelium/rooms/${EXP_ID}-after/plan-tasks.md 2>/dev/null || true

# Stop the after-case loops
pkill -f "mycelium await --loop --room ${EXP_ID}-after" || true
```

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

def count_episode_msgs(transcript):
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

ep_path = base / f"{exp}-after" / "episode-transcript.md"
if ep_path.exists():
    ec = count_episode_msgs(ep_path.read_text())
    print(f"after  — episode message types: {ec}")
PY
```

**What these numbers mean for the Summary table:**
- `before room chat messages` ≈ negotiation moves (every chat turn is a decision)
- `after episode replies` = negotiation moves (the accept/reject/counter-offer actions the aligner interprets)
- `after room chat messages` = narration overhead only — agents explain reasoning around each move
- Aligner addresses are protocol infrastructure, not comparable to anything in the before case

Use `before room chat` vs `after episode replies` as the apples-to-apples move count.
Use `after room chat` as a separate "narration overhead" metric if desired.

Write the report to `~/.mycelium/rooms/${EXP_ID}/evaluation.md`:

```markdown
## Persona Before-and-After: {scenario} — {EXP_ID}

### Persona Set
| Agent | Preference File | Strategy File |
|-------|----------------|---------------|
| ... | ... | ... |

### Summary
| Metric | Before (Chat) | After (Mycelium) |
|--------|-----------------|-----------------|
| Consensus reached? | ... | ... |
| Plan compiled? | n/a | ... |
| Negotiation moves | {before room msgs} | {after episode replies} |
| Chat/reasoning messages | {before room msgs} | {after room msgs} |
| Rounds | n/a | {aligner rounds} |
| Issues explicitly identified | ... | ... |
| Issues resolved | ... | ... |
| Overall score | X/5 | X/5 |

### Success Criteria
| Criterion | Before | After | Delta |
|-----------|--------|-------|-------|
| ... | X/5 | X/5 | +/-N |

### Qualitative Analysis

**Before (unstructured chat):**
- What worked:
- What failed:
- Did persona identity survive unstructured chat? (did agents stay in character?)

**After (Mycelium-mediated):**
- What worked:
- What failed:
- Did the strategy protocol (JSON counter-offers, convergence rules) produce better outcomes?
- Did the compiled plan (`plan/tasks.md`) accurately capture the agreement?

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
         ~/.mycelium/rooms/${EXP_ID}-after/episode-transcript.md \
         ~/.mycelium/rooms/${EXP_ID}-after/plan-tasks.md; do
  [ -f "$f" ] || continue
  echo "=== $f ==="
  grep -inE 'sk-[a-z0-9]|ghp_|gho_|bearer [a-z0-9]|api[_-]?key.*[=:]|password.*[=:]|/Users/|/home/' "$f" | head -5 || echo "  (clean)"
done
```

The transcripts are particularly worth scanning — agent narration may include
filesystem paths, shell output, or tool results. Err on the side of redacting.

If anything lights up, redact or skip the gist. **Always ask the user before uploading.**

Stage everything under unique names to avoid filename collisions, then push as a gist:

```bash
STAGE=$(mktemp -d)
EVAL_DIR=~/.mycelium/rooms/${EXP_ID}
cp "$EVAL_DIR/evaluation.md" "$STAGE/evaluation.md"
# Transcripts — prefer copies in eval dir (written by Phase 5), fall back to live room dirs
for label in before after; do
  for fname in transcript.md episode-transcript.md plan-tasks.md; do
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
# Stop any resident loops still running for this experiment
pkill -f "mycelium await --loop --room ${EXP_ID}-" || true

# Preserve transcripts into evaluation dir before deleting rooms
# (required by summarize_experiments.py for issue recall/F1 scoring)
mkdir -p ~/.mycelium/rooms/${EXP_ID}
for label in before after; do
  src=~/.mycelium/rooms/${EXP_ID}-${label}
  dst=~/.mycelium/rooms/${EXP_ID}
  [ -f "$src/transcript.md" ]         && cp "$src/transcript.md"         "$dst/${label}-transcript.md"
  [ -f "$src/episode-transcript.md" ] && cp "$src/episode-transcript.md" "$dst/${label}-episode-transcript.md"
  [ -f "$src/plan-tasks.md" ]         && cp "$src/plan-tasks.md"         "$dst/${label}-plan-tasks.md"
done
echo "Transcripts preserved in ~/.mycelium/rooms/${EXP_ID}/"

# Remove experiment workspaces
rm -rf ~/.mycelium/experiments/${EXP_ID}-*

# Delete rooms
mycelium room delete "${EXP_ID}-before" -f 2>/dev/null || curl -sf -X DELETE "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-before"
mycelium room delete "${EXP_ID}-after"  -f 2>/dev/null || curl -sf -X DELETE "$MYCELIUM_API_URL/api/rooms/${EXP_ID}-after"

# Clean up temp dirs
rm -rf "$PERSONAS_DIR"
rm -f /tmp/exp_personas_before.json /tmp/exp_personas_after.json
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
| `mycelium room create` returns 400 | Room name already exists | Use unique `$EXP_ID` prefix or delete existing room first |
| After-case agents chat instead of using the protocol | Strategy block not in SOUL.md, or skill not installed | Check the after-case SOUL.md has the `negotiate:` block; verify `mycelium adapter add claude_code --workspace ...` ran for the workspace |
| `curl` to backend fails | Wrong port | Read from `~/.mycelium/config.toml` |
| Resident loop never picks up an address | `claude` not on PATH, or `await` handle mismatch | Check the loop's log (`~/.mycelium/experiments/<agent>/after.log`); confirm the `--handle` matches the summoned agents |
| Ticks/addresses never arrive (after case) | aligner not registered or LLM down | `mycelium engine ls -r <room>`; `mycelium status` → llm |
| Aligner never stops (runs to the cap) | NEGMAS termination regression | it must stop at unanimity, never run out the step cap |
| No `plan/tasks.md` after convergence | plan compiler outage | check backend logs; fail-soft should still emit the raw `issue=value` agreement |
