# START HERE — Cognition Engines as first-class citizens (the `engine` reframe)

> **Status: design agreed, Stage A foundation in progress.** Continues the SAO-mediator
> track (`START_HERE_MEDIATOR*.md`). This doc captures a re-architecture the Rung-2 live
> validation forced into the open: the aligner/mediator is currently backend code behind a
> reserved handle — a "meta-agent" — which **contradicts the project's own thesis** that a
> cognition engine is *an agent in the MAS, not backend code*. This is the plan to make it real.

## The problem

`AlignerEngine` (`fastapi-backend/app/services/aligner.py`) is instantiated in `main.py` and
wired to `room_channel_manager.on_summon`, keyed off a reserved handle string
(`ALIGNER_HANDLE="aligner"`). Consequences, all confirmed live:

- It is **not a registered entity** — no manifest, not in `agent ls`, not created by any command.
- It is **not viewable as a room citizen** — its turn-prompts and verdict never reach the
  `/messages` store the room/UI read (they only hit the persister log).
- Its config is **global env** (`ALIGNER_BRAIN`, `ALIGNER_PI_OPENSHELL`), not per-instance.
- Its brain **can't run where `pi` lives** — the mediation executes in the backend container,
  which doesn't ship `pi`, so `ALIGNER_BRAIN=pi` crashes on `` `pi` not found ``.

`START_HERE_MEDIATOR.md` states the intended end state outright: *"the cognition-engine becomes
an agent in the MAS, not backend code."* The current shape is a transitional Step-7 artifact
(bible §10: "the cheap backend listens and **summons** the engine"). It's time to close the gap.

## The model — a first-party runtime family, not an "adapter"

Traditional adapters (`claude_code`, `cursor`, `openclaw`, `hermes`) **bridge to a third-party
runtime we don't own**. A cognition engine is the opposite — **first-party**: our NEGMAS loop,
our brain. Making it an "adapter" alongside `claude_code` is a category error.

Instead: **one first-party runtime family — `engine` — into which we register a variety of
Cognition Engines**, exactly the bible §10 family ("SIEP converge, SAB bargain, TFP
team-formation"). Engines are their own first-class noun:

```
# external-runtime agent (unchanged):
mycelium agent create worker-1 --adapter claude_code --cwd … --room X

# first-party cognition engine (new):
mycelium engine create mediator-1 --kind aligner --room X
mycelium engine ls --room X
```

- `--kind` is the extensibility axis — `aligner` today; `bargainer`, `team-former`, a drift
  evaluator later — with **no new plumbing per CE**.
- Internally an engine **reuses the agent-manifest infrastructure** so it's a real routable room
  participant: `adapter="engine"`, plus a `kind` field for the CE. Stored at
  `agents/<handle>` like any agent, shows up as a citizen.

## Why this is the right fix (it *dissolves* the four first-run gaps)

The gaps Julia logged on PR #435 are mostly **symptoms of the meta-agent shape**, not
independent bugs. Making the engine first-class removes them:

| Gap (PR #435 comments) | Dissolved by |
|---|---|
| No CLI to summon the aligner | `mycelium engine invoke` / `@mention` a registered engine — same path as any agent |
| `mycelium config set` doesn't expose aligner settings | brain/kind live in the **engine's manifest**, per-instance (different rooms, different brains) |
| `pi` not in the backend container | the engine's runtime runs **where the daemon runs — the host**, where `pi` is installed (Stage B) |
| `openshell` not in the container | same as `pi` — a host concern, not a container one (Stage B) |
| mediator messages invisible in the room | a registered engine **posts as itself** like any citizen |

## Two stages

Level-2 (runtime on the host) can't be reached in one hop — the NEGMAS *core* (`mediator.py`)
is clean (only `negmas` + `settings` + `offer_snap`), but the **drive loop**
(`aligner.py:mediate` + `_slim_turn`) is welded to backend services (`RoomChannelManager`,
`persister.log`, `l9_episode`, episode lifecycle), and `negmas` is a heavy host dep
(matplotlib/scipy/pandas). So:

### Stage A — first-class registration + visibility (mediation still backend-side)
- **Protocol:** `engine` added to `AGENT_ADAPTERS`; `AgentManifest` gains `kind` (the CE type);
  a `backend_engine` lifecycle so the **daemon skips** engine manifests (the backend still owns
  the run in this stage).
- **`EngineIntegration`** (`integrations/engine/`): build_manifest/register/describe + the
  (mostly no-op) install facet, mirroring the minimal cursor/hermes shape.
- **CLI:** a new `mycelium engine` command group (`create`, `ls`, `invoke`, `rm`) — sugar over
  the agent-manifest write with `adapter=engine, kind=<ce>`.
- **Backend recognition:** `main.py`/`room_channels` stop keying the engine off the reserved
  `ALIGNER_HANDLE`; instead `on_summon` fires the aligner run when the summoned handle is a
  registered **engine of kind `aligner`** in that room. (Reserved handle retired.)
- **Visibility:** the engine's prompts + verdict are written to the `/messages` store (not just
  the persister log) so the negotiation is followable in the room/UI.
- Delivers: engines in `agent ls`/`engine ls`, `engine invoke`, per-engine config, visible
  turns. `pi`-on-host (gaps re: container) still pending Stage B.

### Stage B — relocate the runtime to the host (the real Level 2)

**Built + unit-tested (`mycelium/engine/`, live-transport pending):**
- `mediator.py` — the NEGMAS SAO core ported to the CLI package; `llm_sync` →
  `build_litellm_brain(model, api_key, base_url)` (host LLM config, not backend settings). Verified
  running: drives to agreement and terminates below the cap (`test_engine_mediator.py`).
- `offer_snap.py` (copied), `brain.py` (the Pi brain), `mycelium[engine]` extra (negmas, litellm).
- `runtime.py` — `EngineDrive` (the drive loop over an **injected `EngineChannel` seam**: discover →
  `@`-address one agent/turn → interpret → step → emit `commit:converged`), `SlimEngineChannel` (the
  live transport), and `run_engine(handle, room, kind, participants, openings, brain, …)` — a
  launchable unit that connects as `@handle`, drives, closes. Drive logic unit-tested with a fake
  channel (`test_engine_runtime.py`); the SLIM transport is validated live.

**The remaining seam — daemon dispatch (a design fork + live-only work):**
The daemon must, on an engine `@`-mention, run the drive. Two models, pick live:
- **(A) connector reuses its session** — the engine gets a connector; on `@`-mention it runs
  `EngineDrive` over the connector's own session, routing inbound agent replies to the drive's
  `receive` (a "drive-active" mode on the connector loop). No second connection.
- **(B) independent connection + watcher** — a room watcher detects the `@`-mention and launches
  `run_engine` (its own SLIM session). Matches `run_engine` as written, but needs a detector and
  the backend to invite a non-connector engine into the group.
Then: retire the backend `on_summon` mediation for engines (a `ENGINE_RUNTIME=host|backend` switch
during transition) so it doesn't double-run. This is the exact class of async-SLIM code whose bugs
only surfaced live in Rung 1 — build it against a running stack.

**Once wired, this dissolves the remaining `pi`/`openshell`-in-container gaps** (the engine runs
where the daemon + `pi` live).

## Fixed decisions
- Cognition engines are a **first-party `engine` runtime family**, `--kind` selecting the CE —
  **not** a per-CE adapter, **not** backend special-casing.
- Engines are **real room citizens**: registered manifest, in `ls`, invokable, post as
  themselves.
- The reserved `ALIGNER_HANDLE` special-case is **retired** — an engine is summoned like any
  agent, by its own handle.
- **No SAV / drift-validator engine** (that repo's validator is a mess; not porting it). If we
  ever want drift signals, a later `--kind drift` engine is the home — but not now.

## References
- The mediator track + live findings: `docs/START_HERE_MEDIATOR_RUNG2_VALIDATION.md`.
- The gaps this addresses: PR #435 comments.
- Sibling inspiration (bargaining side only, NOT SAV): `outshift-open/ioc-scale-cf-cognition-engines`.
- Direction memory: `project_mediator_pi_negmas`, `project_cfn_teardown_l9_pivot`.
