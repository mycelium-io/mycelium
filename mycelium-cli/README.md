# mycelium-cli

The `mycelium` command: the human's scripting surface, and the **whole**
agent-side participation surface.

Installed standalone as a `uv` tool, so it **cannot import the backend**. Where
it needs something the backend also has, it carries its own copy and a frozen
contract in `contracts/` keeps the two from drifting — both suites assert
against the same file, so a divergence turns a unit test red rather than
silently breaking the wire.

## What lives here

- `src/mycelium/commands/` — one module per CLI verb. `participate.py` is the
  one to read first: `await` and `respond` are the entire coordination
  primitive.
- `src/mycelium/integrations/` — one package per agent runtime family, each with
  its install/registration code and an `assets/` bundle of the instructions that
  teach that runtime how to participate.
- `src/mycelium/slim/` — the CLI's copy of the SLIM + L9 wire primitives.
- `src/mycelium/docs/` — markdown that is the **source of truth** for the docs
  site; the HTML in `docs/` is generated from it.
- `src/mycelium/docker/` — the compose files `mycelium up` / `install` drive.

## Boundaries worth knowing

- **A spoke is a thin client.** Memory commands resolve against the hub over
  HTTP. Nothing is cached locally, so an unreachable hub is reported plainly
  instead of being answered from something stale.
- **An adapter installs knowledge, not a process.** Mycelium never starts an
  agent. An adapter drops instructions; the runtime stays the user's, kept woken
  by looping `await` → reason → `respond`.
- **Anything user-visible here is documentation.** The adapter `assets/` are
  read by agents at runtime, and `src/mycelium/docs/` renders to the public
  site — both go stale the same way code comments do.

## Working in it

Install, the quality gate, and the docs-regeneration command are in the repo
root `CLAUDE.md`.
