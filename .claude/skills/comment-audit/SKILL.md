---
name: comment-audit
description: Audit code comments and inline documentation for temporal/historical notes, overly long narration, and over-referencing of external artifacts (issues, PRs, plan steps). Reviews the current PR diff by default, or the whole codebase with --all. Use when the user says /comment-audit or wants to tidy up comment cruft.
---

# Comment Audit

Catch the three recurring comment smells that agents tend to write and flag (or
fix) them. The job is *comment quality only* — not logic, not bugs, not style of
the code itself. Leave the code alone; only touch comments and docstrings.

## What we're hunting for

A good comment explains **what the code does and why it matters now**, concisely.
Flag comments that drift into any of these:

1. **Temporal / historical notes** — narrating the lineage of the code instead of
   its behavior. "This used to send its own wire message, but as of the big
   refactor that no longer happens." "Previously X, now Y." "To be totally clear:
   none of that lives here anymore." The reader doesn't need the diff history;
   git has it. Describe the current state.

2. **Overly long narration** — exhaustive prose explaining every nuance as if
   narrating a tutorial. Multi-paragraph comments where one sentence would do.
   If the comment is longer than the code it describes and isn't a module/API
   docstring, it's a candidate.

3. **Over-referencing external artifacts** — leaning on GitHub issue numbers, PR
   numbers, plan step IDs, ticket links as if they were self-explanatory.
   "(see also issue #117 and Step 13 of the migration plan)", "TODO: revisit
   once #142 lands." A bare `#142` means nothing to a future reader. Keep a
   reference only when it adds durable context the prose can't.

### The canonical example

This comment manages all three at once:

```
## This Command class used to send its own wire message and mutate
## Ship.position locally, but as of the big refactor in PR #128 (see also
## issue #117 and Step 13 of the migration plan) that no longer happens.
## To be totally clear: none of that lives here anymore. The activation
## now rides on PlayerInputs, and the position mutation is handled entirely
## by the shared /sim system, which runs the very same deterministic step
## on both the client and the server so that prediction and reconciliation
## line up frame-for-frame the way Lightyear expects them to.
## TODO: revisit all of this once #142 finally lands.
```

Should become:

```
## This Command class is a thin shim: the wire activation rides
## `PlayerInputs` and the `Pos` mutation runs in `/sim` on both sides.
```

That's the bar: keep the load-bearing "what it does now," drop the history, the
narration, and the issue numbers.

## Use a cheap model

This is high-volume, low-judgment pattern-matching — exactly what a small model
is good at. **Dispatch the audit to a Haiku subagent** rather than reading every
file yourself. Use the `Agent` tool with `subagent_type: Explore` and
`model: haiku`. For a large scope, fan out several Haiku agents in parallel
(one batch of files each) in a single message. Never burn a large model on this.

## Steps

1. **Determine scope.**
   - Default: the current PR / branch diff. Resolve the base and list changed
     files:
     ```bash
     base=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)
     git diff --name-only "$base"...HEAD -- '*.py' '*.ts' '*.tsx' '*.js' \
       '*.go' '*.rs' '*.gd' '*.toml' '*.sh'
     ```
     If there's no diff against the base (e.g. uncommitted work), fall back to
     `git status` / `git diff --name-only HEAD`.
   - `--all` flag: audit the whole codebase instead. Enumerate tracked source
     files with `git ls-files` (apply the same extension filter). This is a big
     job — fan out Haiku agents in parallel and warn the user it's broad.

2. **Decide mode.** Default is **report-only** (flag findings, don't edit). If the
   user passed `--fix` or asked you to fix them, apply edits after the audit.

3. **Dispatch the audit.** Send the file list (in batches for `--all`) to Haiku
   subagent(s) with this rubric. Each agent returns, per finding:
   `file:line` · which smell(s) (1/2/3) · the offending comment · a tightened
   rewrite. Tell the agents to **only** report comments/docstrings, to skip
   genuinely useful comments, and to never flag code.

   When scoped to a PR diff, instruct agents to focus on comments **in or near
   the changed lines** — don't flag pre-existing comments untouched by the PR
   unless `--all` is set.

4. **Consolidate & report.** Group findings by file. For each, show the current
   comment and the suggested rewrite. Lead with a one-line count
   (`N comments flagged across M files`). If nothing was found, say so plainly.

5. **Fix (if requested).** Apply the rewrites with `Edit`. Only change comment
   text — never the surrounding code. After editing Python, the comment changes
   are no-ops for behavior, but still run the repo's formatter on touched files
   so nothing drifts:
   ```bash
   cd fastapi-backend && uv run ruff format <files>   # or mycelium-cli
   ```
   Then summarize what changed. Don't commit unless the user asks.

## Guardrails

- **Don't over-correct.** Module-level docstrings, public API docs, and a comment
  that explains a genuinely non-obvious *why* are good — leave them. The target
  is cruft, not all prose.
- **Keep durable references.** An issue link that points to a still-relevant
  design discussion can stay; a stale `TODO: #142` after a one-line fix should
  go. Use judgment.
- **Comments only.** This skill never changes logic. If you notice a real bug
  while auditing, mention it separately — don't fix it here.
