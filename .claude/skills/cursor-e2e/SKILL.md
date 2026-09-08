---
name: cursor-e2e
description: Run end-to-end smoke tests for the Mycelium cursor adapter. Verifies cursor-agent prereqs, the resident participation loop (mycelium await --loop --exec) picking up an @-mention and posting a reply, workspace asset drift/healing, auth-failure handling, and an aligner-mediated negotiation with a resident cursor agent. Use when validating the cursor integration on a fresh install, after touching cursor-family code (`integrations/cursor/**`), or after upgrading `cursor-agent` itself.
argument-hint: "[--quick | --full | --coord]"
---

# Cursor Adapter End-to-End Testing

Validate the cursor adapter against the **resident-runtime** model. An agent is
your own live `cursor-agent` session, kept woken by `mycelium await --loop --exec
<cmd>` (await → reason → respond → await). The loop *is* the wake — there is no
daemon and no cold-spawn. This skill focuses on the cursor-specific surface:
`cursor-agent` prereqs, the workspace assets (`.cursor/rules/mycelium.mdc` +
`AGENTS.md`), auth-failure handling, and a resident cursor agent negotiating
through the aligner.

The general `e2e` skill covers stack health, memory, and the operator-driven
negotiation walk. Cursor is **untested / unverified**; treat green here as
necessary, not sufficient.

> **Cold-start-on-demand is deferred.** Waking a handle when no runtime is
> resident (herdr integration + per-agent identity, #446) does not exist yet. An
> `@`-mention to a non-resident handle waits on the durable transcript cursor
> until a runtime awaits. Every dispatch phase keeps a resident loop running.

## Arguments

- `--quick` — Prereqs + single resident round-trip (< 2 min)
- `--full` — Quick + workspace asset drift + auth failure path (~ 4 min)
- `--coord` — Full + aligner-mediated negotiation with a resident cursor agent (~ 6 min)
- No argument — defaults to `--full`

## Prerequisites

```bash
# 1. cursor-agent on PATH
which cursor-agent
cursor-agent --version

# 2. Authenticated on this host. cursor-agent stores its access/refresh tokens
#    at ~/.config/cursor/auth.json (NOT ~/.cursor/cli-config.json — that file
#    holds session metadata only, the token field there has been removed).
ls ~/.config/cursor/auth.json
python3 -c "import json,os; p=os.path.expanduser('~/.config/cursor/auth.json'); j=json.load(open(p)); print('authenticated' if j.get('accessToken') else 'NOT LOGGED IN')"

# 3. Adapter installed + backend reachable
mycelium adapter add cursor
mycelium doctor --mode auto
```

**Fail criteria**: any missing → run `cursor-agent login` and `mycelium adapter
add cursor` before proceeding.

## The resident-loop harness

Every dispatch phase runs the agent as a resident loop: a tiny per-turn handler
reads the turn JSON on stdin and answers with `mycelium respond`, and the loop
keeps it woken. The handler here shells out to a one-shot `cursor-agent -p` to
reason over the prompt — the choice of handler, not a daemon, drives the wake.

```bash
mkdir -p /tmp/cursor-e2e-workspace
cat > /tmp/cursor-e2e-workspace/reply.sh <<'EOF'
#!/usr/bin/env bash
turn="$(cat)"
room="$(printf '%s' "$turn" | python3 -c 'import sys,json;print(json.load(sys.stdin)["room"])')"
handle="$(printf '%s' "$turn" | python3 -c 'import sys,json;print(json.load(sys.stdin)["handle"])')"
prompt="$(printf '%s' "$turn" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("content",""))')"
answer="$(cursor-agent -p "$prompt" 2>/dev/null)"
mycelium respond --room "$room" --handle "$handle" "$answer"
EOF
chmod +x /tmp/cursor-e2e-workspace/reply.sh
```

(Field names come from `mycelium await --json`; adjust the python extractions if
the turn shape has drifted.)

## Phase 1: Single resident round-trip

Create a cursor agent, verify its workspace assets, run a resident loop, and
confirm an `@`-mention gets a reply.

```bash
mycelium room create cursor-e2e

# --cwd is now OPTIONAL — it's just the session's workspace root. We pass it
# because cursor's rules/AGENTS.md assets live under it.
mycelium agent create cursor-x \
  --adapter cursor \
  --cwd /tmp/cursor-e2e-workspace \
  --room cursor-e2e \
  --description "cursor resident smoke test agent"

# Verify workspace assets dropped
ls /tmp/cursor-e2e-workspace/.cursor/rules/mycelium.mdc
ls /tmp/cursor-e2e-workspace/AGENTS.md
grep -q "<!-- mycelium:start -->" /tmp/cursor-e2e-workspace/AGENTS.md && echo "marker present"

# Start the resident loop
mycelium await --room cursor-e2e --handle cursor-x --loop \
  --exec /tmp/cursor-e2e-workspace/reply.sh &
LOOP_PID=$!

# Address the handle; the resident loop picks it up on its next await.
mycelium respond --room cursor-e2e --handle operator \
  "@cursor-x reply with just the string OK so I know you got this."
sleep 30   # cursor-agent -p is ~10-30s
mycelium room messages cursor-e2e --limit 5
# Expect: a reply from cursor-x containing OK

kill $LOOP_PID 2>/dev/null
```

**Fail criteria**:
- No reply within 60s → the loop isn't awaiting this handle, or `reply.sh` failed. Run `mycelium await --room cursor-e2e --handle cursor-x --json` once by hand.
- "cursor-agent not authenticated" from the handler → user needs `cursor-agent login`.
- Workspace assets missing → `install_workspace_assets` raised silently; check for `NotADirectoryError`.

## Phase 2: Workspace asset drift

Verify the adapter heals `AGENTS.md` when the user adds content outside the marker
fence, and that drift is detected by `mycelium doctor`. (Unchanged by the resident
model — asset management runs at `agent create` time.)

```bash
cat > /tmp/cursor-e2e-workspace/AGENTS.md <<'EOF'
# My project agents

This is content I wrote myself. Mycelium should never touch it.

<!-- mycelium:start -->
(stale mycelium block placeholder)
<!-- mycelium:end -->

## More of my content
This is also mine.
EOF

# Force a re-register by removing + re-creating the agent
mycelium agent rm cursor-x --room cursor-e2e -y
mycelium agent create cursor-x --adapter cursor --cwd /tmp/cursor-e2e-workspace --room cursor-e2e

# Verify: my content preserved, mycelium block refreshed
grep -c "This is content I wrote myself" /tmp/cursor-e2e-workspace/AGENTS.md
grep -c "More of my content" /tmp/cursor-e2e-workspace/AGENTS.md
grep -c "# Mycelium Agent" /tmp/cursor-e2e-workspace/AGENTS.md

# Nuke the .cursor dir and check that doctor surfaces the drift
rm -rf /tmp/cursor-e2e-workspace/.cursor
mycelium doctor --mode auto 2>&1 | grep -A 2 "cursor workspace assets"
```

**Fail criteria**:
- User content lost → `_strip_agents_md_section` too aggressive; should only remove between markers.
- Marker block not refreshed → `_write_agents_md_section` didn't run on re-register.
- Doctor didn't flag the missing rule file → cursor doctor checks not wired up.

## Phase 3: Auth-failure friendly path

Simulate "user installed `cursor-agent` but never ran `cursor-agent login`" and
verify the handler surfaces an actionable error rather than a stack trace.

```bash
cp ~/.config/cursor/auth.json /tmp/auth.backup.json
rm ~/.config/cursor/auth.json

# Resident loop with no auth — the handler's cursor-agent call fails; it should
# respond with a friendly message, not crash the loop.
mycelium await --room cursor-e2e --handle cursor-x --loop \
  --exec /tmp/cursor-e2e-workspace/reply.sh &
LOOP_PID=$!
mycelium respond --room cursor-e2e --handle operator "@cursor-x anything"
sleep 15
mycelium room messages cursor-e2e --limit 3
kill $LOOP_PID 2>/dev/null

# doctor catches the bad state while it's still bad
mycelium doctor --mode auto 2>&1 | grep -A 2 "cursor-agent login"

# Restore auth
cp /tmp/auth.backup.json ~/.config/cursor/auth.json
rm /tmp/auth.backup.json
mycelium doctor --mode auto 2>&1 | grep "cursor-agent login"
# If the restore left auth weird: cursor-agent login
```

**Fail criteria**:
- Loop crashed on the auth error → the handler should catch the failure and respond, not propagate.
- Room shows a Python traceback → handler isn't guarding the `cursor-agent` exit code.
- Doctor didn't flag the missing token → cursor login check not reading `~/.config/cursor/auth.json` `accessToken`.

## Phase 4: Aligner-mediated negotiation

Prove a **resident** cursor agent negotiates to consensus through the aligner. The
cursor side runs the resident loop; the aligner (a backend engine) `@`-addresses
it, the loop reasons and responds, and NEGMAS owns termination.

```bash
ROOM=cursor-align-e2e
mkdir -p /tmp/cursor-ws-designer
cp /tmp/cursor-e2e-workspace/reply.sh /tmp/cursor-ws-designer/reply.sh
mycelium room create $ROOM
mycelium engine create aligner --kind aligner --room $ROOM

mycelium agent create designer --adapter cursor \
  --cwd /tmp/cursor-ws-designer --room $ROOM \
  --description "design-polish-focused negotiator"

# Start the resident loop
mycelium await --room $ROOM --handle designer --loop \
  --exec /tmp/cursor-ws-designer/reply.sh &
LOOP_PID=$!

# Opening positions (counterparty operator-driven, or a second loop)
mycelium respond --room $ROOM --handle planner  "Optimize for ship date"
mycelium respond --room $ROOM --handle designer "Optimize for design polish"

# Summon the aligner; it addresses designer by @mention each round.
mycelium engine invoke aligner "converge on the ship-vs-polish tradeoff" -r $ROOM

# Watch for convergence — the plan compiles before consensus is announced.
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
- Aligner addresses designer but no reply lands → the resident loop isn't awaiting, or `reply.sh`/`cursor-agent` failed; run one `await` by hand.
- Cursor agent ignores the mycelium rules → workspace assets missing; rerun `mycelium agent create designer …` to redrop them.
- Aligner loops to the step cap → NEGMAS termination regression (must stop at unanimity).
- No `plan/tasks.md` after agreement → plan compiler outage; fail-soft emits the raw `issue=value` agreement (check backend logs).

## Cleanup

```bash
for h in cursor-x designer; do
  for room in cursor-e2e cursor-align-e2e; do
    mycelium agent rm "$h" --room "$room" --full -y 2>/dev/null
  done
done
rm -rf /tmp/cursor-e2e-workspace /tmp/cursor-ws-designer
curl -s -X DELETE http://localhost:8000/api/rooms/cursor-e2e
curl -s -X DELETE http://localhost:8000/api/rooms/cursor-align-e2e
```

## Interpreting Failures

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| Resident loop never picks up a mention | loop not awaiting this handle | `mycelium await --room <r> --handle <h> --json` once by hand |
| `--exec` fires but no reply lands | handler didn't call `mycelium respond` | run `reply.sh` with a sample turn JSON on stdin |
| `cursor-agent: command not found` in the loop | binary not on the loop shell's PATH | start the loop from a shell where `which cursor-agent` works |
| Workspace `AGENTS.md` double-merged | `_strip_agents_md_section` regex regression | re-run cursor install tests, esp. `test_cursor_install.py::test_marker_merge_*` |
| `Cursor login expired` in room | token expired — `cursor-agent login` again | `~/.config/cursor/auth.json` `accessToken` |
| Aligner never stops (runs to the cap) | NEGMAS termination regression | it must stop at unanimity |

## When to Update This Skill

- The turn-JSON shape from `mycelium await --json` changes → update `reply.sh`'s field extraction
- New cursor-specific asset dropped or new `cursor-agent` flag → add/extend a phase
- `mycelium await` gains a new loop flag → add a phase exercising it
- The aligner gains a new subkind or termination signal → extend Phase 4
