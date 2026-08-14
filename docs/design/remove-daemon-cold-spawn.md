# Plan: kill stateless respawn, keep the wake — move cold-start to herdr

**Status:** proposal v2 (revised after second-opinion review) — not yet executed
**Branch:** `refactor/remove-daemon-cold-spawn`

## Reframe (this is the important change from v1)

Cold-spawn is **two** things, and only one is bad:

- **(a) cold-start-on-demand** — wake a handle when nothing is resident for it.
  This is a real *capability*, and it's load-bearing for autonomous dispatch
  (the "5am escalation," the board handing work to an agent nobody is watching).
- **(b) statelessness** — each `@mention` runs a fresh `claude -p`, context
  discarded, identity re-taught via a preamble every turn. This is the
  *anti-pattern*.

v1 conflated them and deleted both. **v2 kills (b), preserves (a) — relocated, not
removed.** We are not claiming "we don't need cold-start." We're claiming "stateless
respawn is the wrong *implementation* of cold-start; the right one is waking a
persistent, identity-stable runtime, which is the herdr bet (#446)."

## Honest statement of the regression

Durability ≠ liveness. "The `@mention` isn't lost, it's on the durable cursor" is
true but **not the same as handled** — if nothing ever runs a resident `await` loop
for a handle, the mention waits forever. And the proven runtime makes this concrete:
**Claude Code is turn-based.** `claude -p` runs and exits; an interactive session is
resident only while a human is watching. "An agent is a resident await loop" is *not*
automatic for the one adapter CLAUDE.md calls proven — which is precisely why the
daemon existed.

So the change must ship with a **supported way to be resident**, or it trades a
working autonomy mechanism for a promise. We do that with the bridge below, and we
write the regression down plainly:

> Between this change and herdr dispatch, an `@mention` cannot cold-start a handle
> that has **no runtime running**. Agents you keep resident (via `mycelium await
> --loop`) are woken normally; a handle with zero runtime queues until one comes up.
> Accepted, bounded, and closed by #446.

## Decision: ship the bridge (don't gate, don't punt)

Three options considered:

1. **Gate** — don't delete until herdr dispatch exists. Blocks a clean, correct
   cleanup on an unbuilt spike. Rejected.
2. **Punt** — delete now, tell turn-based users "keep your own loop alive with
   systemd/pm2." This reintroduces the exact setup friction the daemon removed, right
   after the roadmap named setup friction the core problem. Rejected.
3. **Bridge (chosen)** — delete the daemon/cold-spawn machine now, and ship a minimal,
   first-party **resident-runner**: `mycelium await --loop`.

### `mycelium await --loop` (the bridge)

A thin, family-agnostic foreground loop — **not** a daemon. No dispatch routing, no
SLIM connector, no preamble, no per-family spawn, no service install. Roughly:

```
mycelium await --loop --exec "<cmd>"     # run in a terminal, tmux, or a unit the
                                          # USER owns — but the loop itself is ours
# loop body:
#   turn = await(handle)          # blocks; refreshes the lease → shows "resident"
#   <cmd> receives turn (JSON)    # the agent's reasoning runtime; it calls respond
#   repeat
```

- Keeps the handle's presence lease alive → it renders `resident`/`lease` in the
  members panel (the presence work from #520 is the liveness surface for exactly this).
- The **reasoning runtime is pluggable** and is the user's choice of `<cmd>`: a
  persistent Agent-SDK session (context accumulates — the good path), or even
  `claude -p` (stateless, but now that's an explicit user choice, not the framework
  conjuring amnesiacs). The *loop* is first-party and supported; statelessness is no
  longer baked in.
- What it does **not** do: cold-start a handle that isn't running `--loop`. That's the
  parked capability, and it's fine — "start your agent's loop once" is a supported
  first-party motion, unlike "write your own systemd unit."

The `--exec` contract (stdin JSON vs args, respond expectations, abort handling) is the
one new thing to nail down; flag for review.

## Verified facts (checked, not assumed)

- **`slim/member.py` is daemon-only.** Only `daemon/connector.py` imports it;
  `await`/`respond` are pure HTTP and merely name it in a docstring. Dies with the daemon.
- **`engine/` is NOT cold-spawn** (`lifecycle="backend_engine"`, registration only). Keep.
- **`list_agent_handles()` / `load_manifest()`** live in `daemon/dispatch.py` but are
  imported by `engine/host.py` → must move to a neutral module first.
- **No backend/frontend code imports the daemon.**

## KILL LIST (delete outright)

| Path | ~Lines | Why |
|---|---|---|
| `mycelium-cli/src/mycelium/daemon/` (11 files) | 2,783 | connector, dispatch loop, runner, health, install, config, state, preamble, mentions |
| `mycelium-cli/src/mycelium/daemon/service/` | — | launchd/systemd unit templates |
| `mycelium-cli/src/mycelium/slim/member.py` | 602 | daemon-only membership core (verified) |
| `integrations/claude_code/spawn.py` | 258 | `claude -p` cold-spawn |
| `integrations/cursor/spawn.py` | 321 | `cursor-agent -p` cold-spawn |
| `integrations/_spawn_common.py` | 98 | `SpawnRequest/Result`, cold-spawn only |
| `commands/daemon.py` | 334 | `mycelium daemon *` surface |
| Daemon/spawn/connector tests (~17) | ~1,200 | `test_daemon_*`, `test_*_spawn`, `test_cursor_auth`, `test_connector_*` |

**≈ 5,000 lines deleted. Note the statelessness dies; the wake does not.**

## KEEP + REFRAME (surgical edits)

Adapters stop being "cold-spawn targets" and become **"install the mycelium skill so
your agent can `await`/`respond` (and run under `--loop`)."**

| Path | Edit |
|---|---|
| `integrations/base.py` | Remove abstract `.spawn()` + `SpawnRequest/Result`. Keep manifest/register/destroy + install facet. Collapse `LifecycleModel` to **`{backend_engine, resident}`** — keep the `resident` marker (see Q3). |
| `integrations/claude_code/dispatch.py` | Remove `.spawn()` + spawn imports. Keep build/register/destroy + `own_handle`/`disown_handle`. |
| `integrations/cursor/dispatch.py` | Same — **only if** cursor rides the claude_code skill-install path for free (see Q1). |
| `integrations/claude_code/install.py` | Keep skill/hook install. Delete `--step=daemon`. |
| `integrations/engine/dispatch.py` + `engine/host.py` | **Keep.** Repoint `host.py` import to the new neutral module. |
| `commands/agent.py` | Keep create/invoke/ls/show/rm; drop `reload_daemon_service()`. **`agent invoke` reports residence** (see Q2), not a silent post-and-hope. |
| `commands/adapter.py` | Keep thin (add/remove/ls/status); drop `--step=daemon`. Do **not** fold into `agent create` (see Q4). |
| `commands/doctor.py`, `commands/demo.py` | Drop daemon health probes. Update demo's mandatory-cwd comments. |
| `commands/participate.py` | `await` gains `--loop`/`--exec` (the bridge). `respond` unchanged. |
| `protocol.py` | Remove the `check_adapter_requirements` cwd branch — `cwd` optional, not required (see below). |
| `commands/agent.py` (`--cwd`) | `--cwd` becomes optional; keep `cwd` as optional manifest metadata. |

## The one structural move

New `mycelium-cli/src/mycelium/agent_registry.py` holding `list_agent_handles()` +
`load_manifest()` lifted from `daemon/dispatch.py`, so `engine/host.py` no longer
imports the deleted `daemon` namespace. Pure move.

## Drop the mandatory `--cwd` (make it optional)

The cwd requirement exists *only* because cold-spawn launched a fresh process there
per `@mention`. `protocol.py:392` enforces it with that exact justification:

```python
if self.adapter in ("claude_code", "cursor") and not (self.cwd and self.cwd.strip()):
    raise ValueError(f"{self.adapter} agents require a non-empty cwd")
```

Its only load-bearing consumer is `spawn.py` (deleted). So:

- **Remove** the `check_adapter_requirements` cwd branch in `protocol.py` — cwd is no
  longer required for `claude_code`/`cursor`. (Keep the `engine` `kind` requirement.)
- **`agent create --cwd` becomes optional**, not mandatory. No more
  `claude_code agents require a non-empty cwd` on create.
- **Keep the `cwd` field as optional metadata** — it's a useful default dir and it's
  what cursor's `install_workspace_assets(Path(manifest.cwd))` consumes when present.
  With cold-spawn gone it's a hint, not a launch requirement; `--loop` runs wherever
  the user starts it.
- Update `commands/demo.py` comments (they document the old mandatory-cwd rule).

## Decisions (from review)

1. **Adapters** — keep `claude_code` as skill-installer (real value: wires a live/looped
   Claude session into a room). Keep a `cursor` shell **only if** skill-install shares the
   claude_code path for free; otherwise drop it (it was already untested). No unproven
   symmetric shell for symmetry's sake.
2. **`agent invoke`** — not fake-synchronous, but not a silent no-op either. It posts the
   `@mention` **and reports residence**: `@x resident — will pick up on next await` vs
   `@x not resident — queued until a runtime awaits`. Honesty about liveness at the call site.
3. **`LifecycleModel`** — collapse, but **keep `resident`**. The `backend_engine`
   (runs in our backend) vs `resident` (runs in a user/herdr runtime) split *is* the
   liveness distinction users need to see. "Just a manifest + skill" throws it away.
4. **`adapter` surface** — keep it thin, separate from `agent create`. "Wire my
   runtime" (once per machine) and "name an agent in a room" (per room) are different
   concerns; conflating them muddies both.

## Docs / skills / e2e

Update `CLAUDE.md` (the agent model is: register a manifest + skill → run `mycelium
await --loop` → coordinate via `await`/`respond`; cold-start-on-demand is a herdr
capability, #446), `docs/agents.md`, `docs/cross-machine.md`,
`docs/design/agent-provisioning.md`.

**Do not silently delete e2e coverage.** `claude-code-e2e` / `cursor-e2e` currently
prove cold-spawn dispatch; **repoint** them to prove the `--loop` resident path (wake →
reason → `respond` → wake), so "claude_code is proven" keeps meaning something after the
change instead of quietly narrowing to "a human-driven session."

## Explicitly NOT in scope

- No cold-start-from-zero (wake a handle with no runtime). Returns via herdr + D1 (#446).
- No always-on supervisor we own. `--loop` is a foreground primitive; keeping it up
  across reboot/detach is the user's runtime or herdr — but the *loop itself* is supported.

## Risk

Low-to-medium mechanically (daemon is well-isolated; only the two relocated helpers and
`engine` registration reach into it). The real risk is **product**, and the bridge +
honest regression note are how we manage it: we ship the cleanup without opening a silent
hole in autonomous dispatch, and we say out loud what doesn't work until #446 lands.
