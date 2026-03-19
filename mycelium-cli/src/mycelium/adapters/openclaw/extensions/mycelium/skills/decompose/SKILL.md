---
name: decompose
description: Extract structured memories from your current session into a Mycelium room
user_invocable: true
---

# /decompose

Decompose your current session into structured Mycelium memories.

Fungi decompose organic matter into reusable nutrients. This skill does the same with conversation — extracting decisions, work artifacts, context, and procedures from your session and persisting them into the room's collective memory.

## How to run

```
/decompose [room-name]
```

If no room is given, use the active room (`mycelium room use`).

## Extraction schema

Walk through your current session and identify anything that fits these categories. For each finding, run `mycelium memory set <key> "<value>" -H <your-handle>`.

### `decisions/` — Choices made and why

What was decided, what alternatives were considered, what was rejected.

- Key format: `decisions/<slug>` (e.g. `decisions/no-redis`, `decisions/use-agens-graph`)
- Value should include the choice AND the reasoning
- Include negative decisions — what you tried and abandoned, and why

Examples:
```bash
mycelium memory set decisions/no-sqlite "SQLite can't handle pgvector — need real Postgres for integration tests"
mycelium memory set decisions/upsert-by-default "Dropped --update flag, memory set always upserts. Backend has version tracking for conflict detection."
```

### `work/` — What was built or changed

Concrete artifacts: code written, files changed, features implemented.

- Key format: `work/<slug>` (e.g. `work/cli-reference-generator`, `work/auth-middleware`)
- Value should describe what was done, not just name the file

Examples:
```bash
mycelium memory set work/doc-ref-decorator "Added @doc_ref decorator system for registering CLI commands in HTML docs. Generator reads registry and replaces content between codegen markers."
mycelium memory set work/mobile-layout-fix "Fixed negotiation flow steps — switched from flex to positioned counters so inline code elements wrap correctly on mobile."
```

### `status/` — Where things stand

Current state of work in progress, blockers, what's passing/failing.

- Key format: `status/<slug>` (e.g. `status/deploy`, `status/ci`)
- Value should be the current state, not history

Examples:
```bash
mycelium memory set status/ci "All checks passing — backend tests (67 passed, 12 skipped), CLI lint clean"
mycelium memory set status/blocker "Need ioc-cfn-mgmt-plane-svc running to test agent registration flow"
```

### `context/` — Background and constraints

User preferences, project constraints, goals, environment facts that future agents need.

- Key format: `context/<slug>` (e.g. `context/user-goal`, `context/deploy-target`)
- Value should explain WHY this matters, not just state it

Examples:
```bash
mycelium memory set context/typography "Keep Cormorant Garamond + IBM Plex Sans pairing. Only change sizing/rhythm."
mycelium memory set context/protocol-is-value "The CLI skill being a protocol (join-wait-respond-consensus) is by design. Don't change it to an augmentation layer."
```

### `procedures/` — Reusable how-to steps

Steps you figured out that another agent could follow to repeat a task.

- Key format: `procedures/<slug>` (e.g. `procedures/regenerate-cli-docs`, `procedures/deploy`)
- Value should be step-by-step, concrete enough to follow without context

Examples:
```bash
mycelium memory set procedures/regenerate-cli-docs "1. Add @doc_ref decorator to command. 2. cd mycelium-cli && uv run python ../docs/generate_cli_reference.py. 3. Verify with /last-screenshot or browser."
mycelium memory set procedures/ship-pr "1. /precommit. 2. git add specific files. 3. git commit with conventional prefix. 4. git push -u origin branch. 5. gh pr create. 6. gh pr checks --watch. 7. gh pr merge --admin."
```

## Guidelines

- **Be selective** — not everything in a session is worth persisting. Extract what a future agent would need to avoid rediscovering.
- **Be specific** — "fixed the bug" is useless. "Fixed mobile layout — flex on li turned inline code into flex items, switched to positioned counters" is useful.
- **Include negative results** — what you tried and abandoned is as valuable as what worked.
- **Idempotent** — `memory set` upserts, so re-running is safe.
- **Report what you wrote** — after extracting, list the keys you set so the user can review.
