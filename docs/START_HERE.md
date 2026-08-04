# START HERE — Mycelium SLIM-Native Rebuild

You are implementing a major rebuild of the **mycelium** project (repo root:
`/Users/juliavalenti/Documents/GitHub/mycelium`). Everything you need is in one document:

**[`docs/slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md) — read it fully
before touching anything.**

## What this is

Mycelium's coordination layer is being moved off a now-removed closed-source backend
(IOC/CFN) onto AGNTCY **SLIM** (a secure messaging fabric) carrying the **L9** protocol, and
the heavy database is being replaced with local markdown + a JSONL index. The bible is the
complete spec: background, architecture, a repo map of exactly which files to keep/remove/
rework, and a step-by-step build plan.

## How to work

1. Read **Parts I–IV** for orientation (Part I includes a glossary — read it). Then execute
   **Part V (the build plan), Steps 0 → 10, in order.**
2. **Do not advance to step N+1 until step N's Definition of Done is met** and its unit tests
   pass. Every step must leave the project **runnable and green**.
3. **Delete the CFN-coupled tests in Step 0; write new unit tests at the end of each step**
   (each step lists them).
4. The **fixed decisions in Part IV are not up for debate.** The **open questions each have a
   recommended default** — use the default, note that you did, and flag it; don't block.
5. Code/config blocks in the bible are **reference only** (SLIM's own examples, existing
   envelope shapes, ops commands) — **not** implementation to paste. Write the implementation
   yourself, matching the surrounding codebase style.
6. **Verify before you edit:** the file paths in Part III were accurate when written, but
   confirm a file still exists / has the expected shape before modifying it.
7. This is **one cohesive effort, not a phased release** — the step order is a build sequence
   so each step has a foundation, not a shipping plan. Build in order; it all lands together.

**Start now with Step 0 (Rip it out).** After each step, report: what changed, the DoD check,
and test results.

## References

- **Ground truth for SLIM APIs/behavior** — the cloned repos under
  `~/Documents/GitHub/_slim-research/` (`slim`, `slim-bindings`, `slim-a2a-python`,
  `ioc-protocols-models`).
- **Design rationale** for any decision — the companion
  [`docs/coordination-transport-pivot.md`](./coordination-transport-pivot.md).
- Note: `CLAUDE.md`'s "Git for sharing" line is **stale** — see the bible's memory section.

The acceptance goal is the hero demo at the end of Part V. Work toward it one green step at a
time.
