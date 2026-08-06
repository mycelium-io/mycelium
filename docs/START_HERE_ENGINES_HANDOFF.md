# START HERE — Handoff: the cognition-engine reframe + mediator track (PR #435)

> **You are a fresh agent picking up `rung2-pi-openshell` (PR #435 → `slim-native-rewrite`).**
> This is a long-running branch. It carries the SAO-mediator track (Rungs 1–2) **and** a
> re-architecture that turns the aligner from backend "meta-agent" code into a first-class
> **cognition engine** (`mycelium engine`). Read this, then `docs/START_HERE_ENGINES.md` (the
> design) and `docs/START_HERE_MEDIATOR_RUNG2_VALIDATION.md` (the live ledger).

## The one-paragraph state

The SAO mediator works — validated live against real cold-spawned agents (it converged and
**stopped**: the anti-theatre property, proven). Along the way we fixed real bugs (wake-storm,
hallucinate-on-silence, invisible-in-room, misreported-agreement), added a Pi brain seam, retired
the `ALIGNER_MODE` flag, and — the big one — reframed the aligner as a first-class **engine**
(`mycelium engine create --kind aligner`). **Stage A** (engines are registered, backend-recognised,
invokable citizens) is done + unit-tested. **Stage B** (relocate the runtime to the host so it runs
where `pi` lives) is *built and unit-tested* except the **daemon-dispatch seam**, which is a design
fork + live-only work left for you.

## What's DONE + verified (unit-tested, all green)

| Area | What | Where |
|------|------|-------|
| Rung 2 | Pi brain seam (`PiBrain`, `ALIGNER_BRAIN`) | `fastapi-backend/app/services/pi_brain.py`, `aligner.py:_make_brain` |
| — | `ALIGNER_MODE` retired — the mediator IS the aligner (no mode flag) | `aligner.py`, `config.py` |
| Reliability | single-wake (`@`-neutralise), fail-closed-on-silence, room-visibility (`ingest_local`) | `aligner.py`, `mediator.py` |
| Correctness | faithful interpretation: fuzzy `offer_snap` + granular discovery grid (fixes misreported agreement) | `offer_snap.py`, `mediator.py:to_outcome`/`discover_issues` |
| **Engine Stage A** | `engine` adapter family + `kind`; `EngineIntegration` (`backend_engine` lifecycle) | `mycelium-cli/.../protocol.py`, `integrations/engine/`, `integrations/base.py` |
| — | `mycelium engine create / ls / invoke` | `mycelium-cli/.../commands/engine.py` |
| — | backend recognises a registered engine + runs `mediate` **as that handle** (reserved `ALIGNER_HANDLE` demoted to fallback) | `aligner.py:handle_summon`/`_registered_engine_kind`/`mediate` |
| **Engine Stage B** | NEGMAS core + brain + snap ported to the host CLI; `mycelium[engine]` extra | `mycelium-cli/.../engine/{mediator,offer_snap,brain}.py`, `pyproject.toml` |
| — | `EngineDrive` (drive loop over an injected `EngineChannel`), `SlimEngineChannel`, `run_engine(...)` | `mycelium-cli/.../engine/runtime.py` |

Tests: `mycelium-cli` 404+ green (incl. `test_engine*.py`); backend `test_aligner/mediator/offer_snap/pi_brain` green.
Run gates: `cd mycelium-cli && uv run ruff check . && uv run ty check . && uv run pytest tests/ -x -q`
and `cd fastapi-backend && uv run pytest tests/test_aligner.py tests/test_mediator.py tests/test_offer_snap.py tests/test_pi_brain.py -q`.
(Backend full suite has one *unrelated* pre-existing failure: `test_l9_over_slim_roundtrip` `ENOENT`/permission on `/opt/fastembed` in this sandbox.)

## What's NOT done (your work), in priority order

### 1. Finish Stage B — the daemon dispatch seam (the last mile)
`run_engine(...)` is a launchable unit, but nothing calls it. On an engine `@`-mention the daemon
must run the drive. **Design fork — decide, ideally live:**
- **(A) connector reuses its session:** give the engine a connector; on `@`-mention run `EngineDrive`
  over the connector's *own* session, switching the connector loop to a "drive-active" mode that
  routes inbound agent replies into the drive's `receive` (instead of re-dispatching). No 2nd
  connection. *Preferred* — reuses membership/invite that already works.
- **(B) independent connection + watcher:** a room watcher detects the mention and launches
  `run_engine` (its own SLIM session). Matches `run_engine` as written but needs a detector + the
  backend to invite a non-connector engine into the group.
Then flip `EngineIntegration.lifecycle` and **retire the backend `on_summon` mediation for engines**
so it doesn't double-run (suggest an `ENGINE_RUNTIME=host|backend` switch during transition).
Touch points: `mycelium-cli/.../daemon/connector.py` (the `_guarded_inbound`/dispatch loop),
`daemon/dispatch.py`, `integrations/engine/dispatch.py`, backend `aligner.py:handle_summon`.
**This is the exact async-SLIM code whose bugs only surface live (Rung 1) — build it with a node up.**

### 2. Live validation (gated on the stack; can't be done blind)
The whole SLIM-drive layer is unit-tested with fakes but the *transport* needs a running node.
Bring the stack up (see below), then:
- **Stage A acceptance:** `mycelium engine create mediator-1 --kind aligner --room R` →
  `mycelium engine invoke mediator-1 "converge …"` → confirm the backend fires `mediate` **as
  mediator-1** and a real negotiation runs. (Backend-run path; still needs `pi` only if `ALIGNER_BRAIN=pi`.)
- **Gate A (Rung 1 live):** two real `claude_code` agents, opposed openings, summon → converge +
  **stop** + `plan/tasks.md` compiled. Already passed once (`{tech:40%, cap:25%}`) — re-confirm on
  the fixed code, and confirm the **faithful-interpretation** fix (agents agreeing on `30%` now
  record `30`, not `25` — the discretization bug).
- **Gate B (Pi brain):** flip `ALIGNER_BRAIN=pi`; re-confirm. Needs `pi` where the brain runs.
- **Stage B acceptance:** once the dispatch seam lands, the engine runs on the **host** — verify
  `pi`/`openshell` are NOT needed in the backend container.

### 3. Known open bugs (documented, from the live runs — see the VALIDATION doc)
- **Agents cave below hard lines under the mediator's `_BATNA` push** (`mediator.py:_BATNA`) — this
  is literally the CE team's "SM-5 Pressure Capitulation". Wants a soften-able knob.
- **`discover_issues` invents phantom issues** not raised by agents (partly mitigated by the "don't
  invent" prompt tweak — re-check live).
- The mediator's own messages reaching the room API: fixed via `ingest_local` for prompts; **verify
  the verdict/commit also surfaces** in `/messages` for a clean UI story.

### 4. The gaps Julia logged on PR #435 (status)
`#4 no summon CLI` → done (`engine invoke`). `#5 config not exposed` → per-manifest via `--kind`
(brain-per-engine still to wire). `#1/#2/#3 pi/openshell in container` → **deliberately not patched**
— Stage B dissolves them (engine on host). Do NOT bundle `pi` into the backend image; finish Stage B
instead.

## Bring the stack up (from `SMOKE_TEST_HANDOFF.md`)
```
docker compose -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml up -d --build slim mycelium-backend
```
(No `mycelium-db` — SLIM-native has no database. Services are `slim` + `mycelium-backend`; frontend
via `ui` profile.) The fastembed model layer re-bakes into the backend image (the disk-heavy part —
**watch disk; we ran out twice this session**). Daemon runs on the **host**: `mycelium daemon run`.
LLM config lives in `~/.mycelium/.env` (backend reads it); `mycelium config set llm.* && mycelium config apply`.

### Operational gotchas (learned the hard way)
- **Raise `ALIGNER_ROUND_TIMEOUT_S` to 90–150s** for real cold-spawns; the 30s default turns real
  replies into timeouts (which used to hallucinate — now fails closed).
- **Setup order:** register agents → `agent invoke` each once (joins connectors + seeds openings) →
  **then** summon. Summoning before connectors join = no one to address.
- **Backend restarts lose in-memory channel/member state** — after a recreate, re-invoke agents to
  rejoin before summoning. Avoid rebuilding mid-negotiation.
- **`LOG_LEVEL: DEBUG`** in `compose-dev.yml` floods with litellm noise; drop to `INFO` while
  debugging (revert before committing — it's a tracked file).

## Ground rules for this work (from the human, Julia)
- **Engines are first-party CEs, not adapters.** `--kind` is the extensibility axis. Never make
  the aligner a user-selectable worker runtime.
- **Pi is for OUR internal agents only** (the mediator/engines). User agents keep their own runtime.
- **No SAV / drift-validator engine** — that sibling repo's validator (`ioc-scale-cf-cognition-engines`
  `semantic_validation/`) is a mess. The *taxonomy* (PM/SM failure modes: PM-3 Repetition = theatre,
  SM-5 Capitulation) is a useful *lens*, and their `offer_validation.py` snap was worth porting — but
  don't build the PM/SM evaluator fleet.
- **Theatre ≠ "converge fast."** The mediator is *designed* to converge fast (that kills theatre),
  but a "converged" deal can still be bad (capitulation/asymmetric). Keep that lens; don't over-build.
- Be honest about proven-vs-not; the human values the ledger over false "done".

## Key references
- **Design:** `docs/START_HERE_ENGINES.md`. **Live ledger + bugs:** `docs/START_HERE_MEDIATOR_RUNG2_VALIDATION.md`.
- **Why the mediator:** `docs/START_HERE_MEDIATOR.md`. **Stack up:** `docs/SMOKE_TEST_HANDOFF.md`.
- **Memory:** `project_mediator_pi_negmas` (direction + all live findings).
- **PR:** #435. **Sibling (bargaining-side inspiration only, NOT SAV):** `outshift-open/ioc-scale-cf-cognition-engines`.
