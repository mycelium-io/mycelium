---
name: claude-code-e2e
description: Run end-to-end smoke tests for the Mycelium claude_code adapter. Verifies claude CLI prereqs, the SKILL.md + workspace install, and the resident participation loop (mycelium await --loop --exec) where a live claude session picks up an @-mention, reasons, and posts a reply back to the room — including a full aligner-mediated negotiation. Use when validating the claude_code adapter after changes to `integrations/claude_code/**`, the participation path (`routes/participate.py`, `mycelium await`/`respond`), or after upgrading the `claude` CLI itself.
argument-hint: "[--quick | --full | --coord]"
---

# Claude Code Adapter End-to-End Testing

Validate the claude_code adapter against the **resident-runtime** model. An agent
is no longer cold-spawned by a daemon; it is your own live `claude` session, kept
woken by `mycelium await --loop --exec <cmd>` (await → reason → respond → await).
The loop *is* the wake. This skill exercises the claude_code-specific surface:
the adapter install (SKILL.md + workspace assets), the resident loop picking up
an `@handle` mention, and a full aligner-mediated negotiation with a resident
claude agent on one side.

The general `e2e` skill covers stack health, memory, and the operator-driven
negotiation walk; this one proves a real `claude` session drives its own turns.

> **Cold-start-on-demand is deferred.** Waking a handle when no runtime is
> resident (herdr integration + per-agent identity, #446) does not exist yet. An
> `@`-mention to a non-resident handle simply waits on the durable transcript
> cursor until a runtime awaits. Every phase below keeps a resident loop running.

## Arguments

- `--quick` — Prereqs + install + single resident round-trip (< 2 min)
- `--full` — Quick + notes persistence across turns (~ 4 min)
- `--coord` — Full + aligner-mediated negotiation with a resident claude agent (~ 5 min, requires funded API credits)
- No argument — defaults to `--full`

## Prerequisites

```bash
# 1. claude CLI on PATH
which claude
claude --version

# 2. Authenticated (claude stores its session under ~/.claude/.credentials.json)
ls ~/.claude/.credentials.json && echo "claude credentials present"

# 3. Adapter installed (SKILL.md + workspace assets; NO daemon)
mycelium adapter add claude-code
ls ~/.claude/skills/mycelium/SKILL.md && echo "mycelium skill present"

# 4. Mycelium backend reachable
mycelium doctor --mode auto
```

**Fail criteria**: any missing → run `claude login`, `mycelium adapter add
claude-code`, or `mycelium up` before proceeding.

## The resident-loop harness

Every phase runs the agent as a resident loop. Write a tiny per-turn handler that
reads the turn JSON on stdin and answers with `mycelium respond`, then keep the
loop alive in the background. The simplest handler shells out to a one-shot
`claude -p` to reason over the prompt — but note this is now a *choice of
handler*, not a daemon: the loop, not a background service, owns the wake.

```bash
mkdir -p /tmp/cc-e2e-workspace
cat > /tmp/cc-e2e-workspace/reply.sh <<'EOF'
#!/usr/bin/env bash
# Reads the turn JSON on stdin; extracts the prompt; reasons; responds.
turn="$(cat)"
room="$(printf '%s' "$turn" | python3 -c 'import sys,json;print(json.load(sys.stdin)["room"])')"
handle="$(printf '%s' "$turn" | python3 -c 'import sys,json;print(json.load(sys.stdin)["handle"])')"
prompt="$(printf '%s' "$turn" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("content",""))')"
answer="$(printf '%s' "$prompt" | claude -p "$prompt" --output-format text 2>/dev/null)"
mycelium respond --room "$room" --handle "$handle" "$answer"
EOF
chmod +x /tmp/cc-e2e-workspace/reply.sh
```

(The exact turn-JSON field names come from `mycelium await --json`; adjust the
python extractions if the shape has drifted.)

## Phase 1: Single resident round-trip

Keep a resident loop, `@`-mention the handle, verify the reply lands.

```bash
mycelium room create cc-e2e

# --cwd is now OPTIONAL — it's just the session's working dir. We pass it so
# reply.sh is on a known path.
mycelium agent create cc-x \
  --adapter claude_code \
  --cwd /tmp/cc-e2e-workspace \
  --room cc-e2e \
  --description "claude_code resident smoke test agent"

# Start the resident loop in the background: await → run reply.sh → await
mycelium await --room cc-e2e --handle cc-x --loop \
  --exec /tmp/cc-e2e-workspace/reply.sh &
LOOP_PID=$!

# Now address the handle. The resident loop picks it up on its next await.
mycelium respond --room cc-e2e --handle operator \
  "@cc-x reply with the literal string 'OK from cc-x' and nothing else."
sleep 25
mycelium room messages cc-e2e --limit 5
# Expect: a reply from cc-x containing "OK from cc-x"

kill $LOOP_PID 2>/dev/null
```

**Fail criteria**:
- No reply in 60s → the loop isn't awaiting this handle, or `--exec` never fired. Run `mycelium await --room cc-e2e --handle cc-x --json` once by hand: does the mention come back?
- Loop exits immediately → `--exec` script non-executable or erroring; run `reply.sh` with a sample turn JSON on stdin.
- "claude: command not found" inside the loop → the shell running the loop lacks claude on PATH.

## Phase 2: Notes persistence across turns

A resident session accumulates memory the normal way: it writes to the room's
shared memory, and later turns read it back. There is no cold-start to lose state
across — but a resident loop must still persist facts to memory, not just to its
in-process context, because the loop can be restarted.

```bash
mycelium await --room cc-e2e --handle cc-x --loop \
  --exec /tmp/cc-e2e-workspace/reply.sh &
LOOP_PID=$!

# Turn 1: write a fact to memory
mycelium respond --room cc-e2e --handle operator \
  "@cc-x record that I love bananas using 'mycelium memory set', then confirm."
sleep 30
mycelium memory ls --room cc-e2e   # expect a new memory entry

# Restart the loop (simulates the session being re-woken)
kill $LOOP_PID 2>/dev/null
mycelium await --room cc-e2e --handle cc-x --loop \
  --exec /tmp/cc-e2e-workspace/reply.sh &
LOOP_PID=$!

# Turn 2: read the fact back
mycelium respond --room cc-e2e --handle operator \
  "@cc-x what did I tell you I love? Reply with just the fruit name."
sleep 30
mycelium room messages cc-e2e --limit 3
# Expect: "bananas"

kill $LOOP_PID 2>/dev/null
```

**Fail criteria**:
- Turn 2 doesn't know about bananas → turn 1 wrote to context only, not memory; the handler must persist via `mycelium memory set`.
- `mycelium memory ls` empty after turn 1 → the handler's tool calls didn't reach the backend; check auth + `~/.mycelium/config.toml`.

## Phase 3: Aligner-mediated negotiation (requires funded API credits)

Prove a **resident** claude agent negotiates to consensus through the aligner —
no operator playing its turns. The claude side runs the resident loop; the
aligner (a backend engine) `@`-addresses it, the loop reasons and responds, and
NEGMAS owns termination.

**Prerequisite credit check** — claude's `-p` mode exits 1 when the account is
empty. Probe first:

```bash
echo "" | claude -p "Reply with the literal string OK." --output-format json \
  | python3 -c "import sys,json
r=json.load(sys.stdin)
if isinstance(r,dict) and r.get('is_error'):
    print('FAIL:', r.get('result')); sys.exit(1)
print('credits ok')"
```

**Test**:

```bash
ROOM=cc-align-e2e
mkdir -p /tmp/cc-ws-shipper
cp /tmp/cc-e2e-workspace/reply.sh /tmp/cc-ws-shipper/reply.sh
mycelium room create $ROOM
mycelium engine create aligner --kind aligner --room $ROOM

# One resident claude agent (auth + credits required here).
mycelium agent create shipper --adapter claude_code \
  --cwd /tmp/cc-ws-shipper --room $ROOM \
  --description "ship-date-focused negotiator"

# Start its resident loop.
mycelium await --room $ROOM --handle shipper --loop \
  --exec /tmp/cc-ws-shipper/reply.sh &
LOOP_PID=$!

# The counterparty's opening position (operator-driven, or a second loop).
mycelium respond --room $ROOM --handle polisher "Optimize for design polish"
mycelium respond --room $ROOM --handle shipper  "Optimize for ship date"

# Summon the aligner. It addresses shipper by @mention; the resident loop
# answers each round. NEGMAS stops the instant they agree.
mycelium engine invoke aligner "converge on the ship-vs-polish tradeoff" -r $ROOM

# Watch for convergence: the plan is compiled BEFORE consensus is announced.
for i in $(seq 1 20); do
  if mycelium plan tasks --room $ROOM 2>/dev/null | grep -q '\- \['; then
    echo "converged: plan compiled"; break
  fi
  echo "[$i] still negotiating"; sleep 15
done
mycelium plan tasks --room $ROOM

kill $LOOP_PID 2>/dev/null
```

**Fail criteria**:
- `claude -p` exits 1 with `Credit balance is too low` → API account empty; top up or route to a different LLM provider.
- Aligner addresses shipper but no reply lands → the resident loop isn't awaiting, or `reply.sh` failed; run one `await` by hand and inspect.
- Aligner loops to the step cap instead of stopping on agreement → NEGMAS termination regression (it must stop at unanimity).
- No `plan/tasks.md` after agreement → plan compiler outage; fail-soft should still emit the raw `issue=value` agreement (check backend logs).

## Cleanup

```bash
for h in cc-x shipper; do
  for room in cc-e2e cc-align-e2e; do
    mycelium agent rm "$h" --room "$room" --full --yes 2>/dev/null
  done
done
rm -rf /tmp/cc-e2e-workspace /tmp/cc-ws-shipper
curl -s -X DELETE http://localhost:8000/api/rooms/cc-e2e
curl -s -X DELETE http://localhost:8000/api/rooms/cc-align-e2e
```

## Interpreting Failures

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| Resident loop never picks up a mention | loop not awaiting this handle | `mycelium await --room <r> --handle <h> --json` once by hand |
| `--exec` fires but no reply lands | handler didn't call `mycelium respond` | run `reply.sh` with a sample turn JSON on stdin |
| `claude: command not found` in the loop | loop shell's PATH lacks claude | start the loop from a shell where `which claude` works |
| Notes don't persist across a loop restart | handler wrote to context, not memory | handler must `mycelium memory set` |
| Aligner never stops (runs to the cap) | NEGMAS termination regression | it must stop at unanimity |
| `Credit balance is too low` on every turn | API account empty | top up credits or route to a different LLM provider |

## When to Update This Skill

- The turn-JSON shape from `mycelium await --json` changes → update `reply.sh`'s field extraction
- `mycelium await` gains a new loop flag (e.g. a backoff/`--once` mode) → add a phase exercising it
- The aligner gains a new subkind or termination signal → extend Phase 3
- Claude CLI changes its `-p` output format or auth path → re-validate the prereqs + `reply.sh`
