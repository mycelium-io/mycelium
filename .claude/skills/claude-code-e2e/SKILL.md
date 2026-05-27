---
name: claude-code-e2e
description: Run end-to-end smoke tests for the Mycelium claude_code adapter. Verifies claude CLI prereqs, daemon installation, single-host cold-spawn dispatch, multi-room ownership semantics, notes persistence across spawns, control verbs (status/abort), budget gating, and concurrent dispatch serialization. Use when validating the claude_code adapter after changes to `integrations/claude_code/**`, the cc-daemon, or after upgrading the `claude` CLI itself.
argument-hint: "[--quick | --full | --concurrent]"
---

# Claude Code Adapter End-to-End Testing

Validate the claude_code adapter by exercising the cold-spawn path on real `claude -p` invocations. The general `e2e` skill covers stack health, memory, and negotiation; this one focuses on the claude_code-specific surface: cc-daemon dispatch, the SKILL.md + hooks install (when re-enabled), and the per-handle serialisation invariant.

## Arguments

- `--quick` — Prereqs + single-host basic dispatch (< 2 min)
- `--full` — Quick + notes persistence + control verbs + budget gating (~ 5 min)
- `--concurrent` — Full + concurrent same-handle dispatch (~ 8 min, intentionally noisy)
- No argument — defaults to `--full`

## Prerequisites

```bash
# 1. claude CLI on PATH
which claude
claude --version

# 2. Authenticated (claude stores its session under ~/.claude/.credentials.json)
ls ~/.claude/.credentials.json && echo "claude credentials present"

# 3. cc-daemon installed for this user
ls ~/.config/systemd/user/mycelium-cc-daemon.service 2>/dev/null \
  || ls ~/Library/LaunchAgents/io.mycelium.cc-daemon.plist 2>/dev/null
systemctl --user status mycelium-cc-daemon 2>/dev/null | grep -E "Active|Loaded" \
  || launchctl print "gui/$(id -u)/io.mycelium.cc-daemon" 2>/dev/null | head -5

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
grep -A 5 '\[handles\]' ~/.mycelium/cc-daemon.toml | grep cc-x

# Daemon picked up the new handle?
mycelium daemon status | grep cc-x || echo "WARN: handle not in daemon view"

# Invoke
mycelium agent invoke cc-x "Reply with the literal string 'OK from cc-x' and nothing else."
sleep 25
mycelium catchup --room cc-e2e --limit 5
```

**Fail criteria**:
- No reply in 60s → check `~/.mycelium/logs/cc-daemon.log` for `dispatch @cc-x`
- "not owned by this daemon" in logs → handle missing from `cc-daemon.toml`; `agent create` didn't kick the daemon
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
mycelium catchup --room cc-e2e --limit 3
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
mycelium catchup --room cc-e2e --limit 5
# Expect: a status message describing the running spawn (handle, elapsed, prompt)

# Abort the running spawn
mycelium agent invoke cc-x "abort"
sleep 5
mycelium catchup --room cc-e2e --limit 5
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
grep "budget exceeded" ~/.mycelium/logs/cc-daemon.log | tail -2
# Expect: at least one budget-denied log line

mycelium catchup --room cc-e2e --limit 5
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

mycelium catchup --room cc-e2e --limit 10
# Expect: cc-b's reply lands ROUGHLY in parallel with cc-a's first reply,
#         then cc-a's second reply lands AFTER cc-a's first reply

# Cross-check with daemon log: per-handle lock acquire/release for cc-a
grep -E "lock|dispatch @cc-a" ~/.mycelium/logs/cc-daemon.log | tail -10
```

**Fail criteria**:
- Two `claude` processes ran in cc-a's cwd simultaneously → `state.lock_for(handle)` regressed
- cc-b waited for cc-a's first spawn before starting → lock is global, not per-handle (regression)

## Cleanup

```bash
for h in cc-x cc-broke cc-a cc-b; do
  mycelium agent rm "$h" --room cc-e2e --full --yes 2>/dev/null
done
mycelium daemon unsubscribe cc-e2e 2>/dev/null
rm -rf /tmp/cc-e2e-workspace /tmp/cc-a-ws /tmp/cc-b-ws
curl -s -X DELETE http://localhost:8000/api/rooms/cc-e2e
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

## When to Update This Skill

- New control verb (e.g. `@handle reload`, `@handle quiet`) → add a phase exercising it
- Notes schema changes → update Phase 2 to assert against the new key shape
- Budget enforcement gains a new tier or persistence layer → expand Phase 4
- New per-handle invariant (e.g. CPU caps, network egress controls) → add a phase
