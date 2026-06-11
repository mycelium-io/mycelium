---
name: cursor-e2e
description: Run end-to-end smoke tests for the Mycelium cursor adapter. Verifies cursor-agent prereqs, single-host dispatch, multi-host dispatch through the hub, cross-family negotiation with claude_code/openclaw, workspace asset drift, and auth failures. Use when validating the cursor integration on a fresh install, after touching cursor-family code (`integrations/cursor/**`, `daemon/dispatch.py`, `daemon/runner.py`), or after upgrading `cursor-agent` itself.
argument-hint: "[--quick | --full | --multi-host]"
---

# Cursor Adapter End-to-End Testing

Validate the cursor adapter by exercising the cold-spawn path end-to-end on real hosts. The general `e2e` skill covers stack health, memory, and negotiation; this one focuses on the cursor-specific surface that only `cursor-agent` exercises.

## Arguments

- `--quick` — Prereqs + single-host dispatch only (< 1 min)
- `--full` — Quick + workspace asset drift + auth failure path (~ 3 min)
- `--multi-host` — Full + spoke dispatch through hub + cross-family negotiation (~ 8 min, requires SSH to spoke hosts)
- No argument — defaults to `--full`

## Prerequisites

Before any phase runs, confirm:

```bash
# 1. cursor-agent on PATH
which cursor-agent
cursor-agent --version

# 2. Authenticated on this host. cursor-agent stores its access/refresh tokens
#    at ~/.config/cursor/auth.json (NOT ~/.cursor/cli-config.json — that file
#    holds session metadata only, the token field there has been removed).
ls ~/.config/cursor/auth.json
python3 -c "import json,os; p=os.path.expanduser('~/.config/cursor/auth.json'); j=json.load(open(p)); print('authenticated' if j.get('accessToken') else 'NOT LOGGED IN')"

# 3. Mycelium backend reachable + cursor doctor checks ok
mycelium doctor --mode auto
```

**Fail criteria**: any of these missing → run `cursor-agent login` and `mycelium adapter add cursor --step=daemon` before proceeding.

## Phase 1: Single-host basic dispatch

The minimum viable cursor agent loop: create room → create cursor agent → @-mention → verify response posts back to the room.

```bash
# Setup
mkdir -p /tmp/cursor-e2e-workspace
mycelium room create cursor-e2e
mycelium daemon subscribe cursor-e2e

# Create a cursor agent
mycelium agent create cursor-x \
  --adapter cursor \
  --cwd /tmp/cursor-e2e-workspace \
  --room cursor-e2e \
  --description "smoke test agent"

# Verify workspace assets dropped
ls /tmp/cursor-e2e-workspace/.cursor/rules/mycelium.mdc
ls /tmp/cursor-e2e-workspace/AGENTS.md
grep -q "<!-- mycelium:start -->" /tmp/cursor-e2e-workspace/AGENTS.md && echo "marker present"

# Verify handle owned in daemon.toml
grep -A 5 '\[handles\]' ~/.mycelium/daemon.toml | grep cursor-x

# Invoke via the daemon
mycelium agent invoke cursor-x "Reply with just the string OK so I know you got this." --room cursor-e2e

# Wait for response (cursor cold-spawn is ~10-30s)
sleep 30
# Inspect recent chat messages (point-in-time read)
mycelium room messages cursor-e2e --limit 5
```

**Fail criteria**:
- No response in room within 60s → check `~/.mycelium/logs/daemon.log` for `dispatch @cursor-x` lines
- "cursor-agent not authenticated" in logs → user needs to re-login
- Handle missing from daemon.toml → `mycelium agent create` didn't persist; check `CursorIntegration.register`
- Workspace assets missing → `install_workspace_assets` raised silently; check for `NotADirectoryError`

## Phase 2: Workspace asset drift

Verify the adapter heals AGENTS.md when the user adds content outside the marker fence, and that drift is detected by `mycelium doctor`.

```bash
# Add user content OUTSIDE the mycelium marker block
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
# The mycelium-managed block opens with `# Mycelium Agent` (asset header)
grep -c "# Mycelium Agent" /tmp/cursor-e2e-workspace/AGENTS.md

# Now nuke the .cursor dir and check that doctor surfaces the drift
rm -rf /tmp/cursor-e2e-workspace/.cursor
mycelium doctor --mode auto 2>&1 | grep -A 2 "cursor workspace assets"
```

**Fail criteria**:
- User content lost → `_strip_agents_md_section` is too aggressive; should only remove between markers
- Marker block not refreshed → `_write_agents_md_section` didn't run on re-register
- Doctor didn't flag the missing rule file → cursor doctor checks not wired up

## Phase 3: Auth-failure friendly path

Simulate "user installed `cursor-agent` but never ran `cursor-agent login`" and verify the daemon posts an actionable error rather than a stack trace.

```bash
# Backup the auth file (this is where cursor-agent reads its tokens from at
# spawn time — not ~/.cursor/cli-config.json, that one only holds session
# metadata).
cp ~/.config/cursor/auth.json /tmp/auth.backup.json

# Move auth.json aside so cursor-agent fails to authenticate.
rm ~/.config/cursor/auth.json

# Try to invoke — should post a friendly message in the room, NOT crash the daemon.
mycelium agent invoke cursor-x "Anything" --room cursor-e2e
sleep 15
mycelium room messages cursor-e2e --limit 3

# Confirm doctor catches the bad state while it's still bad
mycelium doctor --mode auto 2>&1 | grep -A 2 "cursor-agent login"

# Restore auth — if the file got recreated, this overwrites it; otherwise mv is fine
cp /tmp/auth.backup.json ~/.config/cursor/auth.json
rm /tmp/auth.backup.json
# Verify
mycelium doctor --mode auto 2>&1 | grep "cursor-agent login"
# If for any reason the restore left auth in a weird state, run:
#   cursor-agent login
```

**Fail criteria**:
- Daemon crashed (check `systemctl --user status mycelium-daemon`) → auth detection raised instead of returning a SpawnResult
- Room shows a Python traceback → `_detect_auth_required` regression
- Doctor didn't flag the missing token → cursor login check not reading the right field

## Phase 4: Multi-host dispatch (requires --multi-host)

Validate that a cursor agent created on a spoke responds to mentions sent from the hub.

**Prerequisites**: SSH access to spoke host (`oclw3` / `oclw5` / similar), mycelium client installed on spoke, spoke pointed at hub's backend.

```bash
HUB_HOST=oclw4  # hub
SPOKE_HOST=oclw3
ROOM=cursor-multi-e2e

# On the hub: create the room (room creation MUST happen on the host running the backend)
mycelium room create $ROOM

# On the spoke: install + create
ssh $SPOKE_HOST bash <<EOF
  # Verify spoke is pointed at the hub
  grep api_url ~/.mycelium/config.toml
  # Subscribe the spoke's daemon
  mycelium daemon subscribe $ROOM
  # Create the agent
  mkdir -p /tmp/cursor-spoke-ws
  mycelium agent create cursor-spoke \
    --adapter cursor --cwd /tmp/cursor-spoke-ws --room $ROOM \
    --description "spoke-side cursor agent"
EOF

# From the hub: subscribe locally + invoke the spoke agent
mycelium daemon subscribe $ROOM
sleep 3
# Cross-host invoke works because agent invoke falls through to the backend
# when the agent isn't in the local mirror (the hub didn't register cursor-spoke).
mycelium agent invoke cursor-spoke \
  "please reply with the hostname you're running on" \
  --room $ROOM

sleep 60  # cursor-agent cold start is slow
mycelium room messages $ROOM --limit 5
# Expect: a message FROM cursor-spoke containing the spoke host's hostname
```

**Fail criteria**:
- No reply from spoke → spoke daemon not subscribed or auth not propagated; check `ssh $SPOKE_HOST mycelium daemon status`
- Reply contains hub's hostname → handle ownership leaked to hub's daemon (both daemons firing on the same handle)
- Spoke daemon logs `unknown adapter` → spoke client out of date; `uv tool install . --force --link-mode=copy` from `~/mycelium/mycelium-cli`

## Phase 5: Cross-family negotiation (requires --multi-host)

Confirm a cursor agent and a counterparty (`openclaw` or `claude_code`) on different hosts can negotiate via IOC, **autonomously** — i.e. without an operator running `mycelium negotiate respond` between rounds. The daemon gained this autonomous-coordination path in 2026-05: the daemon polls `/api/coordination-sessions`, dynamically subscribes SSE to each active session sub-room, and on every `coordination_tick` cold-spawns the owned agent which then calls `mycelium negotiate respond …` itself.

```bash
ROOM=cursor-ioc-e2e

# Hub: create room, register the counterparty locally.
# (claude_code is the recommended counterparty when openclaw isn't running;
# the autonomous flow is identical for both adapters.)
mycelium room create $ROOM
mkdir -p /tmp/claude-hub-ws
mycelium agent create planner --adapter claude_code \
  --cwd /tmp/claude-hub-ws --room $ROOM \
  --description "ship-date-focused negotiation counterparty"

# Spoke: register cursor agent (auth must already be in place — cursor-agent
# stores tokens at ~/.config/cursor/auth.json on the spoke host).
ssh $SPOKE_HOST mycelium agent create designer --adapter cursor \
  --cwd /tmp/cursor-spoke-ws --room $ROOM \
  --description "design-polish-focused cursor side of the negotiation"

# Trigger negotiation (operator's only role: create + join × N).
mycelium session create -r $ROOM
mycelium session join --handle planner -m "Optimise for ship date" -r $ROOM
ssh $SPOKE_HOST mycelium session join --handle designer -m "Optimise for design polish" -r $ROOM

# Watch the autonomous flow play out. Within ~5s of each join the
# corresponding daemon's poller logs:
#   "dynamic subscribe → cursor-ioc-e2e:session:<short_id> (coordination session)"
# Within ~30s of join-window close, ticks arrive in the sub-room and the
# daemon dispatches:
#   "coordination_tick @planner — round=1 action=respond"
#   "dispatch @planner ← CognitiveEngine"
# Same on the spoke for @designer. Rounds advance every 10–30s as each
# agent posts a {"action":"accept"} / "reject" / {"offer":{...}}.

# Poll for terminal state. Typical converging session lands in 6–15 rounds
# (1–4 minutes); the cap is 20 rounds.
for i in $(seq 1 30); do
  STATE=$(curl -s "http://localhost:8000/api/coordination-sessions?limit=20" \
    | python3 -c "import sys,json
data=json.load(sys.stdin)
for s in data:
    if s['parent_room_name']=='$ROOM' and s['state'] in ('complete','failed'):
        print(s['state']); break
else: print('negotiating')")
  echo "[$i] state=$STATE"
  [ "$STATE" = "complete" ] || [ "$STATE" = "failed" ] && break
  sleep 15
done

# Inspect the consensus message
SHORT=$(curl -s "http://localhost:8000/api/coordination-sessions?limit=20" \
  | python3 -c "import sys,json
for s in json.load(sys.stdin):
    if s['parent_room_name']=='$ROOM' and s['state']=='complete':
        print(s['short_id']); break")
mycelium --json room messages "$ROOM:session:$SHORT" --type coordination_consensus --limit 200 \
  | python3 -c "import sys,json
for m in json.load(sys.stdin)['messages']:
    print(m['content']); break"
# Expect: {\"plan\":\"...\",\"assignments\":{...},\"broken\":false}
```

**Fail criteria**:
- No `dynamic subscribe` log on either daemon within 10s of join → daemon didn't reach the poller branch (deployment regression — verify the installed `dispatch.py` contains `poll_coordination_sessions`)
- `dynamic subscribe` fires but no `dispatch @<handle>` on tick → handle not in this daemon's `daemon.toml.handles` (sibling daemon owns it on a different host); confirm with `mycelium daemon ls`
- `dispatch` fires but spawn exits 1 with `Credit balance is too low` (claude) → counterparty's API key is unfunded; switch counterparty or top up
- `dispatch` fires but spawn exits 1 with `SessionEnd hook ... not found` (claude) → stale `~/.claude/settings.json` from an older mycelium-cli; rerun `mycelium adapter add claude-code --reinstall`
- Cursor agent never produces a counter_offer / accept → `cursor-agent` isn't seeing the mycelium rules (workspace assets missing on spoke); rerun `mycelium agent create designer …` to redrop them
- `broken: true` in consensus after 20 rounds → opposing personas locked on incompatible positions; an agent-prompt issue, not coordination — re-run with less polarised intent strings or a higher `n_steps` budget on the CFN side
- `counter_offer_not_your_turn` loops → agent ignored the per-round `allowed_actions` in the tick payload; agent-prompt issue

## Cleanup

```bash
# Hub
mycelium agent rm cursor-x --room cursor-e2e --full -y 2>/dev/null
mycelium agent rm planner --room cursor-ioc-e2e --full -y 2>/dev/null
mycelium daemon unsubscribe cursor-e2e 2>/dev/null
mycelium daemon unsubscribe cursor-multi-e2e 2>/dev/null
mycelium daemon unsubscribe cursor-ioc-e2e 2>/dev/null
rm -rf /tmp/cursor-e2e-workspace

# Spoke (if --multi-host ran)
ssh $SPOKE_HOST mycelium agent rm cursor-spoke --room cursor-multi-e2e --full -y 2>/dev/null
ssh $SPOKE_HOST mycelium agent rm designer --room cursor-ioc-e2e --full -y 2>/dev/null
ssh $SPOKE_HOST rm -rf /tmp/cursor-spoke-ws

# Drop rooms
curl -s -X DELETE http://localhost:8000/api/rooms/cursor-e2e
curl -s -X DELETE http://localhost:8000/api/rooms/cursor-multi-e2e
curl -s -X DELETE http://localhost:8000/api/rooms/cursor-ioc-e2e
```

## Interpreting Failures

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| `cursor-agent: command not found` in daemon log | binary not on daemon's PATH | restart daemon under correct env: `systemctl --user restart mycelium-daemon` |
| Daemon log shows `not owned by this daemon` | handle missing from `daemon.toml` | `mycelium agent create` didn't trigger restart — re-run on this host |
| "agent created" but @-mentions silently drop | daemon snapshot stale | restart daemon manually; verify `restart_daemon_service` is being called |
| Workspace AGENTS.md double-merged | `_strip_agents_md_section` regex regression | re-run cursor install tests, esp. `test_cursor_install.py::test_marker_merge_*` |
| `Cursor login expired` in room | token expired — `cursor-agent login` again | check `~/.config/cursor/auth.json` `accessToken` |
| Cross-host mention not delivered | spoke daemon not subscribed to room | `mycelium daemon ls` on spoke must show the room |
| Cross-family negotiation never starts | session/room mas_id not set | `mycelium doctor` flags Room MAS IDs |

## When to Update This Skill

- New cursor-specific feature in `integrations/cursor/` (e.g. new `cursor-agent` flag, new asset dropped) → add a phase that exercises it
- New daemon-side regression caught in production → add a fail-criteria row
- New adapter family that can negotiate with cursor → add a cross-family phase
