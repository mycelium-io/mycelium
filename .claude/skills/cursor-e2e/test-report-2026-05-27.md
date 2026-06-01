# Cursor Manual E2E — Test Report

**Date**: 2026-05-27
**Branch**: `feat/cursor-integration`
**PR**: [#332](https://github.com/mycelium-io/mycelium/pull/332)
**Operator**: assisted run, in-session
**Backend**: v1.0.14rc3 on hub
**Mycelium CLI**: local dev install (`uv tool install . --force --link-mode=copy`) on all three hosts

## Environment

| Role | Host | Notes |
|------|------|-------|
| Hub | `oclw4` | Runs backend, IOC mgmt plane, OpenClaw gateway, one cursor agent |
| Spoke | `oclw3` | Spoke client + cc-daemon pointed at hub backend; one cursor agent |
| Spoke | `oclw5` | Spoke client + cc-daemon pointed at hub backend; one cursor agent |

All three hosts: `cursor-agent` ≥ 0.x on PATH, `cursor-agent login` completed once.
SSH config entries on hub for both spokes.

---

## Tests Executed (10 / 10 passed)

Each test below was run against the live three-host setup with the on-branch
CLI installed. "Pass" means the success criteria for the test were met as
defined when the test was scoped; bugs found while running are called out
inline.

### Test 1 — Two cursor agents on same host, different cwds

**Probes**: Per-handle workspace isolation; daemon dispatches each agent into the right cwd; manifest cwd matches what `cursor-agent --workspace` resolves to.

**How**: Created `cursor-x` (cwd `/tmp/ws-x`) and `cursor-y` (cwd `/tmp/ws-y`) on the same host, both in room `cursor-e2e`. Mentioned each with prompt "write your handle to a file named me.txt in your cwd". Verified `/tmp/ws-x/me.txt` and `/tmp/ws-y/me.txt` contained the right handle each.

**Result**: PASS — files landed in the correct workspaces. No cross-contamination.

**Bug surfaced**: **#4** (daemon doesn't reload on `agent create`) — second `cursor-y` created after daemon startup wasn't dispatched until `systemctl --user restart mycelium-cc-daemon`. Fixed in commit `5dc8fda`.

---

### Test 2 — Cursor + claude-code coexist on hub (lifecycle refactor proof)

**Probes**: The lifecycle-discriminator refactor — both cold-spawn families dispatched through the same daemon loop without per-family branching.

**How**: On the hub, registered one cursor agent + one claude_code agent in the same room. Mentioned both in one message: `@hub-cursor and @hub-claude please each reply with your adapter type`.

**Result**: PASS — both responded; daemon log showed `dispatch @hub-cursor` and `dispatch @hub-claude` in parallel, each going through `integration.spawn(request)` on the right `Integration` subclass.

**Bug surfaced**: **#1** (claude_code hooks crash) when `mycelium adapter add claude-code` was re-run for the test. The `_resolve_asset("hooks", family="claude_code")` raised because the bundled assets dir was deleted in an earlier privacy cleanup. Worked around by `mkdir hooks` during the test; properly fixed in commit `5dc8fda` by guarding the resolution behind a non-empty `_CLAUDE_CODE_HOOKS` check.

**Bug surfaced**: **#2** (kebab/snake adapter naming) — `mycelium agent create --adapter claude-code ...` rejected the hyphenated spelling that `mycelium adapter add claude-code` accepted. Fixed in commit `5dc8fda` by normalising `-` → `_` before the membership check.

---

### Test 3 — AGENTS.md marker-merge with pre-existing user content

**Probes**: Non-destructive merge of the mycelium section into a user's existing `AGENTS.md`; idempotent on re-register.

**How**: Pre-seeded `/tmp/ws-merge/AGENTS.md` with user content above and below the mycelium markers, plus a third section without markers. Ran `mycelium agent create cursor-merge --cwd /tmp/ws-merge`. Inspected the resulting file. Then `mycelium agent rm cursor-merge --full` and re-created.

**Result**: PASS — user content above/below preserved verbatim; the mycelium section between the markers was refreshed each time; markerless content untouched.

---

### Test 4 — Notes persistence across cold-spawns

**Probes**: Per-agent notes file under `~/.mycelium/rooms/<room>/agents/<handle>/notes.md` is loaded into the preamble on every spawn so the agent has memory.

**How**: First mention asked `cursor-x` to write "I love bananas" using `mycelium memory set`. Verified the memory landed in the backend. Then `cursor-x abort` (to be safe), wait, then second mention `what did I tell you I love?`.

**Result**: PASS — second cold spawn answered "bananas", confirming the preamble loaded the agent's notes from the room memory.

---

### Test 5 — `mycelium agent invoke` routes via cc-daemon identically to @-mention

**Probes**: `agent invoke` shouldn't be a second code path — it should drop the same `@handle prompt` into the room and let the daemon dispatch.

**How**: Sent identical prompts via `mycelium room post --response "@cursor-x say hi"` and `mycelium agent invoke cursor-x "say hi"`. Compared room messages + daemon log.

**Result**: PASS — both produced identical daemon log entries (`dispatch @cursor-x in cursor-e2e ← cli-user`) and the replies were structurally identical (modulo the model's nondeterminism).

---

### Test 6 — `mycelium doctor` + `mycelium adapter status cursor`

**Probes**: Doctor surfaces cursor-specific health (binary, login, workspace assets); adapter status describes the installed cursor adapter.

**How**: Ran both commands on the hub.

**Result**: PARTIAL — `mycelium adapter status cursor` worked; `mycelium doctor` had **no cursor checks at all**. Surfaced **bug #5**, fixed in commit `5dc8fda` by adding `_check_cursor_agent_binary`, `_check_cursor_login`, `_check_cursor_workspace_assets`.

**Re-run after fix**: PASS — three cursor checks now appear under the Adapters section; all skip cleanly when the adapter isn't registered.

---

### Test 7 — Auth-failure friendly path (on `oclw5`)

**Probes**: An unauthenticated `cursor-agent` doesn't crash the daemon or post a stack trace — it posts an actionable error to the room.

**How**: On `oclw5`, ran `cursor-agent logout` to clear the token, then mentioned the spoke's cursor agent from the hub. Then re-authenticated and re-mentioned.

**Result**: PASS — daemon log emitted `cursor auth required for @<handle>`; the room received `daemon error: cursor-agent is not authenticated. Run cursor-agent login once interactively...`. After re-auth, the next mention worked normally.

---

### Test 8 — Daemon restart resilience mid-dispatch

**Probes**: systemd's `Restart=on-failure` actually fires; in-flight cursor-agent processes survive a daemon kill (or aren't orphaned uncleanly); subsequent mentions dispatch normally.

**How**: Started a long-running cursor mention (asked the agent to write a 200-word essay), then `systemctl --user kill -s SIGTERM mycelium-cc-daemon` on `oclw3` during the spawn.

**Result**: PASS with caveat — the daemon restarted automatically (~10s later via `RestartSec=10`); the in-flight cursor-agent process continued to completion and posted its result to the backend directly (not via the daemon). Subsequent mentions dispatched normally after the restart.

**Caveat surfaced as bug #6**: "Orphan cursor-agent on daemon kill" — direct `kill -9` of the daemon PID (not via systemctl) leaves the cursor-agent child running outside the cgroup. Fixed in commit `5dc8fda` by walking `state.running` on graceful shutdown and SIGTERM/SIGKILLing each.

---

### Test 9 — Nonexistent cwd → clean error

**Probes**: `mycelium agent create --adapter cursor --cwd /does/not/exist` should fail loudly with a friendly message, not crash. AND must not leave orphan handle ownership in `cc-daemon.toml`.

**How**: Attempted `mycelium agent create cursor-broken --adapter cursor --cwd /this/dir/does/not/exist --room cursor-e2e`. Inspected `cc-daemon.toml` after the failure.

**Result**: PASS for the user-facing error message (`cursor agent cwd '...' is not a directory — create it first`).
**FAIL** on the leak check — `cursor-broken` was persisted in `cc-daemon.toml`'s `handles` array. Surfaced **bug #3**, fixed in commit `5dc8fda` by reordering `CursorIntegration.register()` so `install_workspace_assets` (which validates cwd) runs BEFORE the handle claim.

---

### Test 10 — Concurrent same-handle dispatch serialisation

**Probes**: Two mentions to the same cursor agent in quick succession must serialise — `state.lock_for(handle)` returns a per-handle `asyncio.Lock`. Two cursor-agent processes in the same cwd would race over `.cursor/`.

**How**: Sent a message containing `@cursor-x first task: count to 5. @cursor-x second task: count to 3.` Watched daemon log for lock acquire/release and process spawn timestamps.

**Result**: PASS — second spawn waited until first completed; both completed in order. Daemon log showed serial dispatch, not parallel.

---

### Cross-host bonus — Spoke agent dispatched from hub

**Probes**: A cursor agent registered on `oclw3` responds to `@cursor-spoke` mentions posted on the hub. Handle ownership is correctly scoped to the spoke (hub's daemon doesn't dispatch it).

**How**: Created `cursor-spoke` on `oclw3` in a room subscribed by both daemons. Mentioned from `oclw4`.

**Result**: PASS — only the spoke daemon dispatched; reply posted back to the room from the spoke and propagated to the hub via SSE.

---

### Cross-family bonus — Cursor (spoke) negotiating with OpenClaw (hub) via IOC

**Probes**: A cursor agent and an openclaw agent on different hosts can complete an IOC-mediated negotiation. The negotiation engine doesn't care which adapter is on which side.

**How**: Started session in shared room. Hub openclaw `planner` joined with `Optimise for ship date`; spoke cursor `designer` joined with `Optimise for design polish`. Drove accept loop until consensus.

**Result**: PASS — consensus reached with assignments populated, broken=false. Both agents produced counter-offers and accepts via their respective dispatch paths.

**Side findings during this test** (not bugs, just noise):
- OpenClaw plugin had to be reinstalled (`mycelium adapter add openclaw --reinstall`) because the bundled plugin manifest on the hub was older than what `mycelium agent add` writes. Already known; not a cursor-specific issue.
- A stale `deep-observability` plugin path in `~/.openclaw/openclaw.json` blocked gateway restart; manually removed. Unrelated to cursor.

---

## Bugs Surfaced (Summary)

| # | Bug | Severity | Commit |
|---|---|---|---|
| 1 | `claude_code/install.py` crashes resolving missing `hooks` asset dir | Medium (blocks `adapter add`) | `5dc8fda` |
| 2 | `agent create --adapter claude-code` rejects kebab spelling that `adapter add` accepts | Low (UX paper cut) | `5dc8fda` |
| 3 | `cursor` `register()` leaks handle into `cc-daemon.toml` when cwd missing | Medium (silent state corruption) | `5dc8fda` |
| 4 | `agent create`/`rm` don't reload daemon → new agents not dispatched | High (silent failure on every create) | `5dc8fda` |
| 5 | `mycelium doctor` lacks cursor checks entirely | Low (missing diagnostic) | `5dc8fda` |
| 6 | In-flight cursor-agent processes orphaned on daemon SIGTERM (when not in cgroup) | Low (edge case; covered by cgroup default) | `5dc8fda` |

All six covered by `test_followups_e2e_fixes.py` (11 new tests).

---

## Gaps — Tests to Add

The phases below are **not yet exercised** by `cursor-e2e/SKILL.md` and should
land as additional phases or sibling skills as the cursor surface grows. Each
entry: what it probes / how to exercise / why it matters / suggested priority.

### Priority 1 — High value, easy to add

#### G1. Control verbs for cursor (status / abort)

**Probes**: `@cursor-x status` and `@cursor-x abort` work on cursor agents identically to claude_code (the daemon's control-verb branch is family-agnostic by design — must confirm).

**How**: Kick off a long-running cursor mention. In parallel, send `@cursor-x status` (should reply with elapsed time + current prompt) and `@cursor-x abort` (should terminate the in-flight process).

**Why**: These are the only mechanisms an operator has to introspect/stop a runaway cursor spawn. Untested for cursor today; the claude_code path has integration tests but the cursor `RunningProc` registration was added late.

**Suggested location**: New Phase 4 in `cursor-e2e/SKILL.md` (mirror claude-code-e2e Phase 3).

---

#### G2. Sender allowlist enforcement on cursor agents

**Probes**: `--allow-from @julia,@docs-agent` is honoured by the daemon for cursor agents, identically to claude_code. Mentions from non-allowed senders silently drop with a log entry.

**How**: Create `cursor-private` with `--allow-from @julia`. Mention from `@julia` (should dispatch) and from `@operator` (should be denied with `denied @cursor-private ← @operator (allow_from)` in the log).

**Why**: Pinned at the daemon-dispatch layer (`gate_allow_from`); the cursor path inherits it, but a regression in the manifest threading would silently break access control.

**Suggested location**: Single phase under `cursor-e2e/SKILL.md`.

---

#### G3. Workspace asset upgrade on adapter reinstall

**Probes**: When the bundled `mycelium.mdc` content changes upstream, `mycelium adapter add cursor --reinstall` (or `mycelium agent create --reinstall` if we add it) should refresh the rule file in every registered cursor agent's cwd without disturbing `AGENTS.md` user content.

**How**: Manually edit `assets/cursor_rules/mycelium.mdc` in the installed package to add a sentinel comment. Run the reinstall path. Verify the sentinel appears in every agent's workspace rule file AND that AGENTS.md user content is preserved.

**Why**: Today's cursor install is per-agent (drops at `agent create`); we don't have a "refresh all my cursor agents" operation. As the rule file evolves the operator has to `agent rm && agent create` for each. Either we test the current behaviour and document the workaround OR we add a refresh primitive.

**Suggested location**: Could become a `mycelium adapter refresh cursor` command + a phase in the skill.

---

#### G4. Two cursor agents sharing one cwd

**Probes**: Two different cursor handles registered with the same cwd. Workspace asset install is idempotent. The per-handle lock keeps them from racing in the same workspace.

**How**: Register `cursor-a` and `cursor-b` both at `/tmp/shared-ws`. Mention both at once with prompts that touch the same file.

**Why**: We tested per-handle isolation (different cwds). The opposite case — shared cwd, different handles — is plausible (a team with one repo + multiple roles) and tests a different invariant: the daemon's per-handle lock no longer protects against concurrent file writes when the cwd is shared.

**Suggested location**: Likely a "known limitation" + warning in the install path rather than a test that should pass.

---

#### G5. Budget gate is permissive for cursor (documented zero-cost)

**Probes**: Cursor reports no `$` cost, so the daemon's budget tracker accumulates `$0` per call. Setting `--budget 0.01` on a cursor agent should NOT block subsequent dispatches the way it does for claude_code.

**How**: Create `cursor-cheap --budget 0.01`. Mention twice. Confirm both dispatch (vs claude_code where the second would be denied).

**Why**: Pinned in the CHANGELOG ("`--budget` is stored on the manifest for symmetry but not enforced"). A unit test exists, but an integration test confirms the daemon's budget code path actually returns `0.0` from `cursor`'s `SpawnResult` and doesn't accidentally accumulate something else (e.g. token-count interpreted as dollars).

**Suggested location**: Phase in `cursor-e2e/SKILL.md` paired with a counter-test in `claude-code-e2e/SKILL.md`.

---

### Priority 2 — Medium value, more setup

#### G6. Depth-cap across cold-spawn family

**Probes**: `cursor-x` mentioning `cursor-y` mentioning `cursor-x` triggers `gate_depth`'s 60-second depth cap. Same daemon, same cold-spawn loop, must enforce the cap.

**How**: Two cursor agents in the same room with system prompts that always mention the other. Send one bootstrap mention. Watch for `denied @cursor-x ← @cursor-y (depth cap N in 60s)` in the daemon log.

**Why**: Pinned at the daemon layer; cursor inherits it via the lifecycle refactor. A regression in `state.recent_dispatches` deque sizing or sender extraction would silently allow infinite chains.

**Suggested location**: Sibling phase to G1, could be combined.

---

#### G7. Cursor MCP server enablement

**Probes**: `--approve-mcps` on `cursor-agent -p` actually loads MCPs from the user's `~/.cursor/mcp.json` and the agent can call them.

**How**: Add a benign MCP server to `~/.cursor/mcp.json` (e.g. `mcp-server-time` that exposes a `get_time` tool). Mention `@cursor-x what time is it according to the time MCP?`. Verify the response references the MCP-sourced time.

**Why**: Cursor's MCP integration is a core feature; `--approve-mcps` is supposed to auto-approve them in headless mode. Untested today. If `--approve-mcps` regresses or cursor changes the flag, every MCP-using cursor agent silently loses its tool surface.

**Suggested location**: New "Phase 6 — MCP surface" in `cursor-e2e/SKILL.md`, requires test MCP setup.

---

#### G8. Workspace permission failure → friendly error

**Probes**: `cwd` exists but is not writable by the user running the daemon. `install_workspace_assets` should raise a friendly error (not a `PermissionError` stack trace), and the handle should NOT be claimed.

**How**: `chmod 555 /tmp/readonly-ws && mycelium agent create cursor-readonly --cwd /tmp/readonly-ws`.

**Why**: Symmetric to bug #3 (cwd missing). The fix there reordered claim-after-validate, but it only validates `is_dir()`; a non-writable dir would currently pass validation and fail at file-write time, with the handle already claimed.

**Suggested location**: Adjacent to Phase 1 in the skill. May surface bug #3.5.

---

#### G9. Cross-host cursor agent ownership invariant

**Probes**: A cursor manifest synced via git to a second host does NOT get dispatched by the second host's daemon (because the second host's `cc-daemon.toml` doesn't claim the handle).

**How**: Create `cursor-only-on-hub` on the hub. Sync the room manifest dir to the spoke via git (or scp). Confirm spoke's `cc-daemon.toml` does not list the handle. Mention `@cursor-only-on-hub` from the spoke's CLI. Verify: only hub's daemon dispatches; spoke's daemon log shows `skip @cursor-only-on-hub — not owned by this daemon`.

**Why**: The handle-ownership invariant is the only thing preventing duplicate dispatch in multi-host setups. Pinned in `test_daemon_ownership.py` as a unit test, but never verified live.

**Suggested location**: Promotes Phase 4 of the skill from "spoke dispatched from hub" to "ownership-correct cross-host dispatch".

---

### Priority 3 — Edge cases / future-proofing

#### G10. Token expiry mid-spawn

**Probes**: If `cursor-agent`'s session token expires while a process is running, does the spawn fail cleanly or hang?

**How**: Hard to simulate without forcing token expiry. Lower value; document as a known unknown.

---

#### G11. Large prompt handling

**Probes**: What's the max prompt size cursor-agent accepts? Daemon currently passes the full prompt as a positional arg — there's an OS-level argv limit (~128KB on Linux).

**How**: Mention with a deliberately huge prompt (`python3 -c "print('x' * 200000)" | pbpaste …`).

**Why**: Today's daemon would either silently truncate (bad) or fail with `OSError: [Errno 7] Argument list too long`. Either way, the operator sees nothing useful.

---

#### G12. Unicode in handles and prompts

**Probes**: Non-ASCII content in agent names, prompts, and workspace paths round-trips through the SSE → daemon → cursor-agent → SSE pipeline without corruption.

**How**: Create `@デザイナー` with a cwd containing Japanese characters. Mention with an emoji-heavy prompt.

**Why**: Likely works (Python 3, asyncio, JSON SSE all UTF-8), but never explicitly tested. A regression in handle extraction regex or argv encoding would silently break it.

---

#### G13. Cursor CLI flag drift

**Probes**: A `cursor-agent` upgrade that adds/removes/renames a flag (`--workspace`, `--trust`, `--force`, `--approve-mcps`) breaks the daemon. We should detect this in CI by version-pinning `cursor-agent` in a test container, or by parsing `cursor-agent --help` in a smoke test.

**How**: Periodic CI job that runs `cursor-agent --help`, grep for each flag we depend on, fails CI if any are missing.

**Why**: We depend on a binary we don't control. Pure detect-and-warn play.

---

#### G14. Daemon log rotation

**Probes**: cursor-agent produces verbose transcripts. `~/.mycelium/logs/cc-daemon.log` grows unboundedly.

**How**: Run many cursor mentions, watch the log size.

**Why**: Operator quality-of-life. The log isn't logrotated today.

**Suggested location**: Not a cursor-specific concern — should land in the general `e2e` skill or a separate ops skill.

---

## Recommendations for `cursor-e2e/SKILL.md`

The current skill (5 phases) covers:
1. Prereqs
2. Single-host basic dispatch
3. Workspace asset drift
4. Auth-failure friendly path
5. Multi-host dispatch
6. Cross-family negotiation

**Recommended additions** (in priority order):

1. **New Phase 4.5** — Control verbs (G1) + sender allowlist (G2) + depth cap (G6) — three quick checks that share setup.
2. **New Phase 7** — Cursor MCP surface (G7) — requires the test MCP server setup but pins a critical feature.
3. **New Phase 2.5** — Workspace permission failure (G8) — adjacent to the existing asset drift phase.
4. **Expand current Phase 5** — Cross-host ownership invariant (G9) — current phase tests positive dispatch only; expand to also assert the negative (sibling daemon does NOT dispatch).
5. **New Phase 3.5** — Budget-tracker permissiveness for cursor (G5) — paired with the existing auth-failure phase.

The remaining gaps (G3 — asset refresh, G4 — shared cwd, G10-G14) are either:
- Future-feature gates (G3 needs a refresh command first; G4 needs a documented limitation),
- Hard to reliably exercise in a skill (G10-G12),
- Or ops concerns that don't belong in adapter e2e (G13-G14).

---

## Health of the surface today

After the six follow-up fixes in `5dc8fda` landed:

- **Pass rate**: 10/10 on the manual walkthrough.
- **Bugs remaining post-fix**: 0 known.
- **Test coverage**: 36 unit tests across the cursor surface (`test_cursor_install.py`, `test_cursor_dispatch.py`, `test_cursor_spawn.py`, `test_cursor_auth.py`, `test_daemon_cursor_routing.py`); 11 in `test_followups_e2e_fixes.py` covering each bug fix. Full suite: **253 passed**.
- **Manual coverage gaps**: 14 documented above (G1-G14), 5 prioritised for the skill.

The adapter is in shippable shape and the lifecycle-discriminator refactor lands the daemon in a good place for the next family (Gemini / Codex / Aider). The five priority-1 gaps are the recommended next investment if/when this surface gets touched again.
