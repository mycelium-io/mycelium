---
name: claude-code-e2e
description: Run end-to-end smoke tests for the Mycelium claude_code adapter. Verifies claude CLI prereqs, daemon installation, single-host cold-spawn dispatch, multi-room ownership semantics, notes persistence across spawns, control verbs (status/abort), budget gating, concurrent dispatch serialization, and (with funded API credits) autonomous coordination via mycelium-daemon coordination_tick handling. Use when validating the claude_code adapter after changes to `integrations/claude_code/**`, the daemon, or after upgrading the `claude` CLI itself.
argument-hint: "[--quick | --full | --concurrent | --coord]"
---

# Claude Code Adapter End-to-End Testing

Validate the claude_code adapter by exercising the cold-spawn path on real `claude -p` invocations. The general `e2e` skill covers stack health, memory, and negotiation; this one focuses on the claude_code-specific surface: daemon dispatch, the SKILL.md + hooks install (when re-enabled), the per-handle serialisation invariant, and (Phase 6) the autonomous coordination flow where the daemon wakes the agent on every `coordination_tick`.

## Arguments

- `--quick` — Prereqs + single-host basic dispatch (< 2 min)
- `--full` — Quick + notes persistence + control verbs + budget gating (~ 5 min)
- `--concurrent` — Full + concurrent same-handle dispatch (~ 8 min, intentionally noisy)
- `--coord` — Full + Phase 6 autonomous coordination (~ 5 min, requires funded API credits)
- No argument — defaults to `--full`

## Prerequisites

```bash
# 1. claude CLI on PATH
which claude
claude --version

# 2. Authenticated (claude stores its session under ~/.claude/.credentials.json)
ls ~/.claude/.credentials.json && echo "claude credentials present"

# 3. Daemon installed for this user
ls ~/.config/systemd/user/mycelium-daemon.service 2>/dev/null \
  || ls ~/Library/LaunchAgents/io.mycelium.daemon.plist 2>/dev/null
systemctl --user status mycelium-daemon 2>/dev/null | grep -E "Active|Loaded" \
  || launchctl print "gui/$(id -u)/io.mycelium.daemon" 2>/dev/null | head -5

# 4. Mycelium backend reachable
mycelium doctor --mode auto
```

**Fail criteria**: any missing → run `claude login`, `mycelium adapter add claude-code --step=daemon`, or `mycelium up` before proceeding.

## Phase 1: Single-host basic dispatch

Cold-spawn `claude -p` for one `@handle` mention and verify the reply lands in the room.

```bash
mkdir -p /tmp/cc-e2e-workspace
mycelium room create cc-e2e
mycelium daemon subscribe cc-e2e

# Create agent (cwd is required for claude_code — that's where `claude -p` runs)
mycelium agent create cc-x \
  --adapter claude_code \
  --cwd /tmp/cc-e2e-workspace \
  --room cc-e2e \
  --description "claude_code smoke test agent" \
  --budget 1.00

# Verify handle owned (so this daemon, not a sibling, dispatches it)
grep -A 5 '\[handles\]' ~/.mycelium/daemon.toml | grep cc-x

# Daemon picked up the new handle?
mycelium daemon status | grep cc-x || echo "WARN: handle not in daemon view"

# Invoke
mycelium agent invoke cc-x "Reply with the literal string 'OK from cc-x' and nothing else."
sleep 25
mycelium room messages cc-e2e --limit 5
```

**Fail criteria**:
- No reply in 60s → check `~/.mycelium/logs/daemon.log` for `dispatch @cc-x`
- "not owned by this daemon" in logs → handle missing from `daemon.toml`; `agent create` didn't kick the daemon
- "claude: command not found" → daemon's PATH doesn't include the claude install; `systemctl --user import-environment PATH` then restart daemon

## Phase 2: Notes persistence across spawns

`claude_code` agents read/write `~/.mycelium/rooms/<room>/agents/<handle>/notes.md` on every spawn so the agent has persistent memory across cold starts.

```bash
# First spawn: write a note
mycelium agent invoke cc-x \
  "Write 'I love bananas' as a memory using mycelium memory set, then confirm."
sleep 30

# Verify the note landed
mycelium memory ls --room cc-e2e
mycelium memory get agents/cc-x/preferences --room cc-e2e 2>/dev/null || \
  ls ~/.mycelium/rooms/cc-e2e/

# Second spawn: read the note back
mycelium agent invoke cc-x \
  "What did I tell you I love? Reply with just the fruit name."
sleep 30
mycelium room messages cc-e2e --limit 3
```

**Fail criteria**:
- Second spawn doesn't know about bananas → notes not loaded into prompt preamble; check `daemon/preamble.py` integration
- `mycelium memory ls` empty → first spawn's tool calls didn't reach the backend; check agent's auth + `~/.mycelium/config.toml`

## Phase 3: Control verbs (status / abort)

The daemon recognises `@handle status` and `@handle abort` as control verbs that bypass the normal cold-spawn path. They must work even when a regular dispatch is in flight.

```bash
# Kick off a slow dispatch
mycelium agent invoke cc-x \
  "Count from 1 to 10 slowly, sleeping 3 seconds between each number." &
sleep 5

# In parallel: ask for status — should respond immediately, NOT queue behind the count
mycelium agent invoke cc-x "status"
sleep 5
mycelium room messages cc-e2e --limit 5
# Expect: a status message describing the running spawn (handle, elapsed, prompt)

# Abort the running spawn
mycelium agent invoke cc-x "abort"
sleep 5
mycelium room messages cc-e2e --limit 5
# Expect: the count stopped early; abort acknowledged

wait  # let the background invoke return
```

**Fail criteria**:
- status hangs waiting for the count to finish → control verbs not bypassing the per-handle lock; check `daemon/dispatch.py` control-verb branch
- abort didn't kill the running `claude` process → `_handle_abort` not finding the right `RunningProc`

## Phase 4: Budget gating

The daemon enforces the `budget_usd_per_month` cap. Set a tiny budget and confirm subsequent dispatches are denied.

```bash
# Create an agent with a $0.01 monthly cap
mycelium agent create cc-broke \
  --adapter claude_code \
  --cwd /tmp/cc-e2e-workspace \
  --room cc-e2e \
  --budget 0.01

# First invoke probably exceeds the cap on its own
mycelium agent invoke cc-broke "Write a haiku about budgets."
sleep 30

# Second invoke should be denied at the daemon
mycelium agent invoke cc-broke "Write another one."
sleep 5
grep "budget exceeded" ~/.mycelium/logs/daemon.log | tail -2
# Expect: at least one budget-denied log line

mycelium room messages cc-e2e --limit 5
# Expect: room shows a budget-exceeded message (or no second reply at all)
```

**Fail criteria**:
- Second invoke produced a reply → `gate_budget` not summing usage correctly; check `state.budget_used_usd`
- Budget reset between invokes → state lost across SSE deliveries; check that `record_dispatch` increments rather than overwrites

## Phase 5: Concurrent same-handle dispatch (requires --concurrent)

The daemon must serialise mentions to the same handle so two `claude` processes never race over the same cwd. Mentions to *different* handles run in parallel.

```bash
# Two agents, same daemon
mycelium agent create cc-a --adapter claude_code --cwd /tmp/cc-a-ws --room cc-e2e
mycelium agent create cc-b --adapter claude_code --cwd /tmp/cc-b-ws --room cc-e2e
mkdir -p /tmp/cc-a-ws /tmp/cc-b-ws

# Three quick @-mentions in the same message — daemon should:
#  - run cc-a once (one mention)
#  - run cc-b once
#  - serialise the second @cc-a mention behind the first
START=$(date +%s)
mycelium room post cc-e2e --agent operator --response \
  "@cc-a count to 5 and reply. @cc-b reply with 'B'. @cc-a then reply with 'second-a'."

# Wait for both to finish
sleep 90
END=$(date +%s)
echo "elapsed: $((END - START))s"

mycelium room messages cc-e2e --limit 10
# Expect: cc-b's reply lands ROUGHLY in parallel with cc-a's first reply,
#         then cc-a's second reply lands AFTER cc-a's first reply

# Cross-check with daemon log: per-handle lock acquire/release for cc-a
grep -E "lock|dispatch @cc-a" ~/.mycelium/logs/daemon.log | tail -10
```

**Fail criteria**:
- Two `claude` processes ran in cc-a's cwd simultaneously → `state.lock_for(handle)` regressed
- cc-b waited for cc-a's first spawn before starting → lock is global, not per-handle (regression)

## Phase 6: Autonomous coordination (requires funded API credits)

Validate that the daemon dispatches `claude_code` agents on every `coordination_tick` and that the agent runs `mycelium negotiate respond …` itself — no operator in the loop. This is the autonomous-coordination path the daemon gained in 2026-05; it pairs with the `claude_code/spawn.py` `--permission-mode bypassPermissions` flag added at the same time. Together they let cold-spawned claude run shell commands without an interactive approver.

**Prerequisite credit check** — claude's `-p` mode does not fall back gracefully when the API account is empty; spawns exit 1 with `{"is_error":true,"api_error_status":400,"result":"Credit balance is too low"}` and the negotiation runs out the round budget posting daemon errors. Verify credits are present before starting:

```bash
# A trivial probe — must return a real assistant message, not is_error=true.
echo "" | claude -p "Reply with the literal string OK." \
  --output-format json --permission-mode bypassPermissions \
  | python3 -c "import sys,json
r=json.load(sys.stdin)
if isinstance(r,dict) and r.get('is_error'):
    print('FAIL:', r.get('result')); sys.exit(1)
print('credits ok')"
```

**Test**:

```bash
ROOM=cc-ioc-e2e
mkdir -p /tmp/cc-ws-shipper /tmp/cc-ws-polisher
mycelium room create $ROOM
mycelium daemon subscribe $ROOM

# Two claude_code agents on this host (auth + credits required here).
mycelium agent create shipper --adapter claude_code \
  --cwd /tmp/cc-ws-shipper --room $ROOM \
  --description "ship-date-focused negotiator"
mycelium agent create polisher --adapter claude_code \
  --cwd /tmp/cc-ws-polisher --room $ROOM \
  --description "design-polish-focused negotiator"

# Trigger the session — operator's only step.
mycelium session create -r $ROOM
mycelium session join --handle shipper -m "Optimise for ship date" -r $ROOM
mycelium session join --handle polisher -m "Optimise for design polish" -r $ROOM

# Watch the daemon log. Expect within ~5s of joins:
#   dynamic subscribe → cc-ioc-e2e:session:<id> (coordination session)
# Within ~30s of join-window close:
#   coordination_tick @shipper — round=1 action=respond
#   dispatch @shipper ← CognitiveEngine
# Same for @polisher. Rounds advance autonomously — the daemon respawns the
# agent on every tick, the agent runs ``mycelium negotiate respond …``
# inside the spawn, and the negotiation converges (or hits the 20-round cap).

tail -F ~/.mycelium/logs/daemon.log | grep -E "dynamic subscribe|coordination_tick|dispatch @"

# In another shell, poll the session for terminal state:
for i in $(seq 1 30); do
  STATE=$(curl -s "http://localhost:8000/api/coordination-sessions?limit=20" \
    | python3 -c "import sys,json
for s in json.load(sys.stdin):
    if s['parent_room_name']=='$ROOM' and s['state'] in ('complete','failed'):
        print(s['state']); break
else: print('negotiating')")
  echo "[$i] state=$STATE"
  [ "$STATE" = "complete" ] || [ "$STATE" = "failed" ] && break
  sleep 15
done
```

**Fail criteria**:
- `claude -p exited 1. stderr: SessionEnd hook ... not found` → stale `~/.claude/settings.json` from an older mycelium-cli that registered hook scripts the current install doesn't ship. Run `mycelium adapter add claude-code --reinstall` to prune the dead `Stop` / `SessionEnd` entries.
- `claude -p exited 1` with `Credit balance is too low` → API account empty; top up or route to a different LLM provider before retrying.
- `dispatch @<handle>` fires but `mycelium negotiate respond …` never appears in the room → claude's permission layer blocked the shell call. Confirm the spawn line in `claude_code/spawn.py` includes `--permission-mode bypassPermissions`. Without it the agent posts apologetic "command needs approval" broadcasts every round but never moves the negotiation forward.
- `dynamic subscribe` log missing within 10s of the join → daemon doesn't have the coordination-session poller. Reinstall: `cd mycelium-cli && uv tool install . --force --reinstall && systemctl --user restart mycelium-daemon`.
- `dispatch @<handle>` log missing on tick → handle not owned by this daemon. Check `daemon.toml.handles`; if `mycelium agent create` didn't refresh it, run `mycelium daemon restart`.
- `broken: true` after 20 rounds → personas locked on incompatible positions; an agent-prompt issue, not coordination.

## Cleanup

```bash
for h in cc-x cc-broke cc-a cc-b shipper polisher; do
  for room in cc-e2e cc-ioc-e2e; do
    mycelium agent rm "$h" --room "$room" --full --yes 2>/dev/null
  done
done
mycelium daemon unsubscribe cc-e2e 2>/dev/null
mycelium daemon unsubscribe cc-ioc-e2e 2>/dev/null
rm -rf /tmp/cc-e2e-workspace /tmp/cc-a-ws /tmp/cc-b-ws \
       /tmp/cc-ws-shipper /tmp/cc-ws-polisher
curl -s -X DELETE http://localhost:8000/api/rooms/cc-e2e
curl -s -X DELETE http://localhost:8000/api/rooms/cc-ioc-e2e
```

## Interpreting Failures

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| `claude: command not found` in daemon log | daemon's `PATH` doesn't see the claude CLI | `systemctl --user import-environment PATH` then restart daemon |
| Daemon log says `not owned by this daemon` | `agent create` didn't restart the daemon | rerun create OR `mycelium daemon restart` |
| Notes don't persist | preamble injection lost the notes block | check `daemon/preamble.py::build_preamble` |
| Status command hangs | per-handle lock is blocking control verbs | control verbs must run OUTSIDE the lock; check `daemon/dispatch.py` |
| Budget never enforces | `state.budget_used_usd` reset on each spawn | budget is process-lifetime, not persistent; restart erases it (known) |
| Two spawns race in same cwd | lock is global or missing | `state.lock_for(handle)` must return a per-handle `asyncio.Lock` |
| Spawn fails with auth error | `claude` CLI lost its session | `claude login` interactively, then restart daemon |
| `SessionEnd hook ... not found` on every spawn | stale `~/.claude/settings.json` from older mycelium-cli (Phase 6) | `mycelium adapter add claude-code --reinstall` to prune dead `Stop`/`SessionEnd` entries |
| `Credit balance is too low` on every spawn (Phase 6) | API account empty | top up credits or route to a different LLM provider |
| Agent posts "command needs approval" but never runs `mycelium negotiate respond …` (Phase 6) | spawn missing `--permission-mode bypassPermissions` | confirm the flag in `claude_code/spawn.py`, reinstall CLI, restart daemon |
| `dynamic subscribe` log missing on session create (Phase 6) | daemon predates the coordination-session poller | `cd mycelium-cli && uv tool install . --force --reinstall && systemctl --user restart mycelium-daemon` |

## When to Update This Skill

- New control verb (e.g. `@handle reload`, `@handle quiet`) → add a phase exercising it
- Notes schema changes → update Phase 2 to assert against the new key shape
- Budget enforcement gains a new tier or persistence layer → expand Phase 4
- New per-handle invariant (e.g. CPU caps, network egress controls) → add a phase
- New autonomous-coordination signal (e.g. daemon gains a `coordination_X` handler) → extend Phase 6
- Claude CLI changes the permission-mode flag or default → re-validate Phase 6 and update `claude_code/spawn.py`
