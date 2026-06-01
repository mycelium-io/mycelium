# Autonomous Coordination — Test Report

**Date**: 2026-05-28 (cursor validation run) + 2026-05-29 (claude credit-blocked run)
**Branch**: `feat/cursor-integration` (continuation of [#332](https://github.com/mycelium-io/mycelium/pull/332))
**Operator**: assisted run, in-session
**Backend**: v1.0.14rc3 on hub
**Mycelium CLI**: local dev install (`uv tool install . --force --link-mode=copy`) on `oclw4`
**Scope**: validating the cc-daemon's new autonomous-coordination path — agents must respond to `coordination_tick` themselves, no operator-driven `mycelium negotiate respond accept` loop required.

---

## Why this run happened

The 2026-05-27 cross-family negotiation walkthrough ([previous report](./test-report-2026-05-27.md))
passed only because an operator manually drove the accept loop — running
`mycelium negotiate respond accept` on each side after every round. The operator
sitting in the loop hid a real gap: cold-spawn agents (cursor + claude_code)
were never observing `coordination_tick` messages on their own. Those messages
NOTIFY only on the session sub-room channel (`<parent>:session:<id>`), and
`cc-daemon` was subscribed only to parent rooms.

The OpenClaw plugin solves this by polling `/api/coordination-sessions` and
opening an SSE listener per active session. This run validated bringing the
same approach into `cc-daemon`, plus the secondary fixes the validation
surfaced.

## Environment

| Role | Host | Notes |
|------|------|-------|
| Hub | `oclw4` | Backend, IOC mgmt plane (`ioc-cognition-fabric-node-svc` + `ioc-cfn-mgmt-plane-svc`), two cursor agents (`hub-cursor-a` + `hub-cursor-b`), one cc-daemon |

Switched from the planned three-host topology to two-cursor-on-hub for the
autonomous run — the spokes don't have an authenticated `cursor-agent` and the
`claude_code` path was credit-blocked (see Run B). One host is enough to
validate the coordination loop because the daemon's polling is per-process,
not per-host.

---

## Run A — Cursor-only autonomous negotiation (2026-05-28)

### Setup

- Two cursor agents in room `cursor-ioc-e2e` on the hub:
  - `@hub-cursor-a` cwd `/tmp/ws-a`, intent "optimise for design polish"
  - `@hub-cursor-b` cwd `/tmp/ws-b`, intent "optimise for ship date"
- Started a coordination session via `mycelium negotiate start --room cursor-ioc-e2e --topic "release plan"`
- **No operator intervention after start** — the hypothesis being tested was
  that the daemon would dispatch each agent on every `coordination_tick`
  and the agent's spawned `cursor-agent -p` would itself run
  `mycelium negotiate respond accept` (or propose / reject).

### Result: PASS — consensus reached, 0 daemon errors

Daemon log signature on the hub:

```
INFO  dynamic subscribe → cursor-ioc-e2e:session:01H… (coordination session)
INFO  coordination_tick round=1 participant=hub-cursor-a action=respond
INFO  dispatch @hub-cursor-a in cursor-ioc-e2e:session:01H… ← CognitiveEngine
INFO  coordination_tick round=1 participant=hub-cursor-b action=propose
INFO  dispatch @hub-cursor-b in cursor-ioc-e2e:session:01H… ← CognitiveEngine
…
INFO  coordination_consensus round=4 broken=false
INFO  dispatch @hub-cursor-a in cursor-ioc-e2e:session:01H… ← CognitiveEngine (consensus)
INFO  dispatch @hub-cursor-b in cursor-ioc-e2e:session:01H… ← CognitiveEngine (consensus)
INFO  dynamic unsubscribe → cursor-ioc-e2e:session:01H… (session no longer active)
```

Backend `coordination-sessions` row reached `state=complete` with non-empty
`assignments` and `broken=false`. Both agents were spawned by the daemon on
every round; both posted their `mycelium negotiate respond …` invocations as
broadcasts in the session sub-room.

### Bugs found and fixed during Run A

The first attempted run did not pass — it surfaced two daemon bugs that block
autonomous operation. Both fixed in this branch and pinned by tests.

#### Bug A1 — `coordination_tick` ignored because daemon wasn't subscribed to the sub-room

**Symptom**: Round 1 fired on the backend (visible in
`/api/rooms/<session>/messages`) but never appeared in the daemon log. The
session sat at `negotiating` for 60 s and timed out.

**Cause**: `cc-daemon` only subscribed to rooms listed in `cc-daemon.toml`.
`coordination_tick` NOTIFY's only on the session sub-room channel, so a
parent-room subscriber misses every tick.

**Fix**: Added `poll_coordination_sessions` to `daemon/dispatch.py` —
periodically (every 5 s) hits `/api/coordination-sessions?limit=200`, derives
the active set (sessions in `waiting` or `negotiating`), and maintains an SSE
subscription per active session in `state.session_room_tasks`. Tracks task
liveness to be idempotent across polls; cancels and drops the entry when a
session leaves the active set. Wired into `daemon/runner.py` as a sibling of
the existing `sse_tasks`.

**Test coverage**: 7 new tests in
[`test_daemon_coordination.py`](../../../mycelium-cli/tests/test_daemon_coordination.py)
under "poll_coordination_sessions — dynamic session sub-room subscription":
subscribes only to live states, ignores rows without `:session:` markers,
idempotent across polls, unsubscribes when sessions leave the active set,
survives a transient backend outage, and exits promptly on `state.stopping`.

#### Bug A2 — `no manifest in local mirror — skipping` for every tick

**Symptom**: After fixing A1, the daemon now received the tick but logged
`no manifest in local mirror — skipping` and didn't dispatch.

**Cause**: `_handle_tick` and `_handle_consensus` called `load_manifest` with
`room_name`, but `room_name` is the session sub-room (`<parent>:session:<id>`)
when the message arrives over the dynamic subscription. Manifests live under
the parent room, not the sub-room.

**Fix**: Both functions now derive the parent: `parent_room =
room_name.split(":session:", 1)[0] if ":session:" in room_name else room_name`,
and use `parent_room` for `load_manifest` / `list_agent_handles` while
preserving `room_name` (the sub-room) for the dispatch context — so the agent's
`mycelium negotiate respond` lands in the right session, not the noisy parent.

**Test coverage**: 4 new tests in `test_daemon_coordination.py` —
"parent-room derivation in tick / consensus" — pin both halves of the
invariant: lookup uses parent, dispatch uses sub-room, and the split is
no-op for non-session room names.

---

## Run B — Claude credit-blocked (2026-05-29)

### Setup (same as Run A)

Replaced the two cursor agents with one `claude_code` agent
(`@hub-claude-a`) on `oclw4` to confirm the same autonomous flow works
across cold-spawn families. Spokes (`oclw3`, `oclw5`) skipped — Claude only
authenticated on the hub.

### Result: BLOCKED — Anthropic API credit exhausted

After two further daemon-side fixes (B1, B2) the spawn path itself worked —
the daemon dispatched `claude -p` per `coordination_tick`, the spawn
ran `--permission-mode bypassPermissions` and didn't stall on tool approval
prompts, and the agent received the round prompt in argv. But the
`claude` CLI then exited with:

```json
{"is_error": true, "api_error_status": 400, "result": "Credit balance is too low"}
```

This is a billing issue on the operator account, not a code bug. The
autonomous-dispatch path is validated through to the `claude -p` invocation;
end-to-end autonomous consensus on `claude_code` will be re-run once the
credit balance is topped up.

### Bugs found and fixed during Run B

#### Bug B1 — claude permission prompts block coordination_tick spawns

**Symptom**: First claude_code-on-hub run produced broadcast messages like
"The command requires user approval" instead of the negotiate response. The
session timed out.

**Cause**: `claude -p` in print mode still respects the user's
`~/.claude/settings.json` permission rules and can stall on the first Bash
tool call awaiting interactive approval. Cold-spawn means there's no terminal
in front of the user; the prompt waits forever.

**Fix**: Added `--permission-mode bypassPermissions` to the `cmd` list in
`integrations/claude_code/spawn.py`. Mirrors what the `cursor` adapter
already does via `--trust --force --approve-mcps`.

**Test coverage**: New file
[`test_claude_spawn.py`](../../../mycelium-cli/tests/test_claude_spawn.py) —
3 tests pinning the exact argv layout: `-p` + prompt as positional, the
`--permission-mode` flag is `bypassPermissions` (not `default` /
`acceptEdits` / `plan`), `--output-format json` for cost parsing, no
broader `--dangerously-skip-permissions` bypass slipped in by accident, and
`--append-system-prompt` carries the identity preamble when a handle is
provided.

#### Bug B2 — `SessionEnd hook ... not found` on every spawn

**Symptom**: After fixing B1, every `claude -p` invocation aborted before
emitting any output:

```
daemon error: claude -p exited 1. stderr: SessionEnd hook
[/home/ubuntu/.claude/hooks/mycelium-session-end.sh] failed: /bin/sh: 1: …
not found
```

`mycelium adapter add claude-code --reinstall` cleaned up the hooks, but
the next reinstall re-added them.

**Cause**: `_CLAUDE_CODE_STALE_HOOKS` correctly listed retired hook scripts
for cleanup. `_CLAUDE_CODE_HOOK_EVENTS` (used by
`_register_claude_code_hooks` to wire entries into `settings.json`) still
listed the same events. Result: every reinstall did a perfect cleanup +
re-registration loop, leaving an entry pointing at a script that the
package no longer ships.

**Fix**: Set `_CLAUDE_CODE_HOOK_EVENTS = []` in
`integrations/claude_code/install.py`. The current adapter doesn't ship
any hooks; the in-process knowledge extractor handles what those wrappers
used to do, with cleaner privacy gates.

**Test coverage**: New file
[`test_claude_install.py`](../../../mycelium-cli/tests/test_claude_install.py) —
4 tests: `_CLAUDE_CODE_HOOK_EVENTS` is empty, `_CLAUDE_CODE_HOOKS` is
empty (so the install loop doesn't try to copy nonexistent assets),
`_CLAUDE_CODE_STALE_HOOKS` covers every retired hook so upgraders get
cleaned up, and the live + stale lists are disjoint (preventing the
cleanup-then-re-add loop from ever recurring).

---

## Documentation updates

The autonomous flow renders the operator-driven accept loop obsolete in
the most common cases. Three skills updated to reflect this:

- `e2e/SKILL.md` — Phase 3 rewritten around the autonomous flow; "Manual
  override" subsection retained for debug / non-daemon-owned counterparties.
- `cursor-e2e/SKILL.md` — Phase 5 (cross-family negotiation) updated;
  expected daemon log signatures added; new fail criteria for autonomous
  failure modes (missing dispatch, credit exhaustion, `:session:` chasing).
- `claude-code-e2e/SKILL.md` — new Phase 6 covering autonomous coordination
  + a pre-flight credit check (the bug B from this run pre-empted); fail
  criteria expanded to cover `SessionEnd hook ... not found` and
  permission-mode regressions.

Internal jargon (the F10 issue ID) removed from skills + source comments;
each reference replaced with a descriptive phrase ("the autonomous-
coordination path the cc-daemon gained in 2026-05") so a reader without
the issue tracker context can still follow.

---

## Bugs Surfaced (Summary)

| # | Bug | Severity | Fix |
|---|---|---|---|
| A1 | cc-daemon never receives `coordination_tick` (subscribed to parent room only) | Critical (silently breaks every autonomous negotiation) | `poll_coordination_sessions` poller in `dispatch.py` + `runner.py` |
| A2 | `_handle_tick` / `_handle_consensus` look up manifests under sub-room name → "no manifest in local mirror" | Critical (every tick skipped even when the agent is registered) | parent-room derivation via `split(":session:", 1)` |
| B1 | `claude -p` stalls on tool-approval prompts during autonomous spawns | High (claude_code can't participate autonomously) | `--permission-mode bypassPermissions` in `claude_code/spawn.py` |
| B2 | Reinstall re-introduces stale hook entries that point at scripts the package no longer ships | High (claude_code spawns abort before any work happens) | empty `_CLAUDE_CODE_HOOK_EVENTS` |

All four covered by the new tests below.

---

## Test additions

| File | New tests | What they pin |
|------|-----------|---------------|
| `tests/test_daemon_coordination.py` | 7 poller + 4 parent-room | Poller subscribes only to live sessions, idempotent across polls, unsubscribes on session exit, survives backend outage, exits on shutdown. Manifest lookup derives parent room; dispatch context retains sub-room. |
| `tests/test_claude_spawn.py` (new) | 3 | `--permission-mode bypassPermissions` flag layout; no broader `--dangerously-skip-permissions` accidentally slipped in; identity preamble appended when handle present. |
| `tests/test_claude_install.py` (new) | 4 | `_CLAUDE_CODE_HOOK_EVENTS` and `_CLAUDE_CODE_HOOKS` are empty; `_CLAUDE_CODE_STALE_HOOKS` covers every retired hook; live + stale sets are disjoint. |

Full suite: **304 passed** (was 253 before the autonomous-coordination work
and 290 after the prior Phase 1-6 fixes; 14 net new tests this branch).

---

## Health of the surface today

- **Cursor autonomous coordination**: validated end-to-end on the hub. Two
  agents reach consensus with no operator intervention.
- **Claude autonomous coordination**: dispatch path validated; final agent
  invocation blocked on Anthropic credit balance. Code-side ready.
- **Operator accept loop**: still works as a manual override and is documented
  as such in all three skills (useful when one side isn't owned by a daemon —
  for example a debugging operator playing the human role).
- **Test coverage**: 14 new tests pin the four bug fixes; full suite green
  (304 passed, 0 errors). `ruff check` + `ruff format` clean on all new
  files. `mypy` clean on all touched files (the 43 errors `mypy src tests`
  reports are all pre-existing in files not touched by this branch).

## Pending follow-ups

1. **Re-run Run B** with claude credits restored, on `oclw4` (auth available)
   — confirms the autonomous loop crosses cold-spawn families end-to-end.
2. **Spoke autonomous validation** — once `cursor-agent login` is run on
   `oclw3` and `oclw5`, repeat Run A across hosts to confirm the polling
   topology works when daemons run on different machines.
3. **OpenClaw <-> cursor autonomous round-trip** — the 2026-05-27 run did
   this with the operator loop; confirm the autonomous path still works
   when one side is the openclaw plugin's existing tick handler.
4. **Coordination poll cadence tuning** — `_SESSION_POLL_INTERVAL_S = 5.0`
   is conservative. Could move to 2 s if the backend `/api/coordination-
   sessions` cost stays cheap; would shave ~3 s off the time-to-first-tick
   on a fresh session.
