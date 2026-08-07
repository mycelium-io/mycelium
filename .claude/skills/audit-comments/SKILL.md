---
name: audit-comments
description: Cheap-model audit of comments and inline docs for temporal/historical narration, overly long prose, over-referencing of GitHub issues / PR numbers / plan-step IDs, and design-justification / conversational residue (comments that defend the approach or echo how the code was steered instead of plainly describing it). Defaults to the current PR diff; pass --all to sweep the whole codebase, --fix to apply the rewrites. Use when the user says "audit comments", "comment cleanup", "tidy comments", "check the comments", or "audit-comments".
user_invocable: true
---

# Audit: Comments & Inline Docs

A focused pass over comments only — **not** logic, not architecture. It hunts the
four comment smells that creep back in over time and tightens them toward the
doctrine: *load-bearing "why" only, matching the surrounding density, no
historical narration, no tracker breadcrumbs.* Comments describe the code plainly.

Mycelium's own convention: **present-tense what/why only in source comments — no
`(#334)`-style tracker breadcrumbs and no historical narration.** Git holds the
lineage; the codebase's design rationale lives in `CLAUDE.md` and the auto-memory
index, not smeared across source comments. This skill enforces that, plus three
sibling smells.

**This runs on a cheap model.** The orchestrator (you) gathers the scope and
dispatches the actual file-reading and review to **Haiku** sub-agents via the
`Agent` tool with `model: "haiku"`. You do not read the files yourself — that's
the whole point, it keeps the audit cheap. You collate the sub-agents' findings
and present them.

---

## The four smells

1. **Temporal / historical narration** — comments that describe the *lineage* of
   the code instead of its current behavior. Tells: "this used to…", "replaces
   the previous…", "now we…", "as of PR#…", "after the refactor…", "previously",
   "no longer", "renamed from…". Git holds the history; the comment describes the
   code as it is.

   Comments that point at the scaffolding of an in-flight migration — build
   plans, staged-rollout labels, "phase/rung N", or any internal process document
   — are this smell, not legitimate references. Such scaffolding is transient; the
   comment describes the code, not the effort that produced it. Rewrite to the
   plain present-tense behavior and drop the pointer.

2. **Overly long / exhaustive prose** — comments that narrate every nuance like a
   YouTube tutorial. A paragraph where a sentence does. Re-explaining the
   language, restating the code line-by-line, or belaboring a point already clear
   from the names.

3. **Over-referencing external artifacts** — decorative, transient references to
   GitHub issues (`#142`), PR numbers (`PR #128`), "Step 13 of the migration
   plan", etc. The smell is **historical** references and **stacked** ones ("see
   also #117 and Step 13"), not references as such.

   **A reference is legitimate — keep it — when it points at a durable artifact
   that genuinely aids the reader:** a named feature/system, a skill
   (`.claude/skills/<name>/SKILL.md`), a design doc (`docs/*.md`), or a source
   module the comment coordinates with (`route.ts:formatTickInstruction`). Those
   carry rationale the code can't. A
   single *forward-pointing* tracking link on a real `TODO`/`FIXME` is also fine.
   Reserve referencing for those load-bearing pointers; strip the decorative ones.
   **Do not propose removing every external reference** — only the ones that
   narrate history or pile on without earning their keep. Calibrate; when in
   doubt, leave it.

4. **Design-justification / conversational residue** — comments that *defend the
   approach* or echo *how the code was steered* instead of plainly describing what
   it does. This is the residue of the design conversation getting baked into the
   file: the comment exists because someone told the agent "do it this way, not
   that way," and the agent wrote the justification down. The reader of this file
   didn't ask for the defense — they want to know what the code does.

   Tells: "Deliberately NOT the X", "This is NOT a Y", "rather than …", arguing
   against an alternative the reader never raised; positioning the file against
   sibling systems for flavor; and editorial flourishes that congratulate the
   design ("Honest geometry", "the clean way"). Contrast with the legitimate
   present-tense "X, not Y" that disambiguates a genuine gotcha a reader would
   otherwise trip on — that stays. The smell is *defending a choice* or
   *re-litigating a rejected alternative*, not a one-clause clarifying contrast.

   Fix: cut to the flat statement of what the code is and the load-bearing why for
   *this* file. If the only reason a sentence exists is to justify the approach
   against another, delete it.

**Canonical bad → good (Python):**

```python
# BAD — all three at once
# This used to route Bedrock models through litellm.acompletion like everything
# else, but as of PR #412 (see also issue #388 and the CFN teardown plan step 4)
# that no longer works — acompletion silently hangs on Bedrock. Now we thread a
# sync completion() through a worker thread instead, which was the whole point ...
# TODO: revisit once #142 finally lands.

# GOOD — thin, current, load-bearing
# litellm.acompletion doesn't work for Bedrock; route Bedrock models through
# threaded sync completion() instead.
```

**Smell #4 — design-justification / conversational residue (TypeScript):**

```ts
// BAD — defends the approach, positions against a sibling, editorializes
// Deliberately NOT parsing the raw tick payload here like the CLI path does.
// We could surface the fields directly, but that would couple the plugin to the
// backend schema, so instead we render a human string — the clean, decoupled way.

// GOOD — flat, describes the code
// The agent only ever sees this formatted string; raw payload fields are rendered
// by formatTickInstruction so the openclaw flow stays in sync with the CLI path.
```

Out of scope: logic bugs, naming, architecture, missing comments (this skill does
not ask for *more* comments). If a comment is fine, leave it. Honest "clean" is a
valid result — don't manufacture findings.

---

## Steps

### 1. Parse flags

- (default) — review only what the **current PR** changed.
- `--all` — sweep every tracked source file in the codebase.
- `--fix` — after the audit, apply the rewrites to the working tree (no commit).
  Without it, this skill is **read-only**: report only.

### 2. Gather the scope

**PR mode (default):**

```bash
BASE=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)
git diff --name-only "$BASE"...HEAD
git diff --name-only            # include uncommitted
```

Filter to source files that carry comments — `*.py *.ts *.tsx *.js *.mjs` — and
**skip generated + vendored + non-source files**:

- generated: the whole OpenAPI client `mycelium-client/**`, any regenerated CFN
  client (`ioc_cfn_svc_api_client/**`), `*.generated.*`, `next-env.d.ts`,
  `*.d.ts`.
- vendored: `fastapi-backend/app/services/l9_models.py` (datamodel-codegen from
  ioc-protocols-models — don't touch its header or generated comments).
- non-source / data: `**/*.json`, `**/node_modules/**`, `.next/**`, `public/**`,
  lock files (`uv.lock`, `pnpm-lock.yaml`, `package-lock.json`),
  `.mycelium/**` (memory data, not source).

In PR mode, hand each agent the **changed files** (and, when `--fix` is off, you
may also pass the unified diff so it only judges *touched* comment regions — a
pre-existing wart in an untouched function isn't this PR's problem).

**--all mode:** list all tracked source files, minus the exclusions above:

```bash
git ls-files '*.py' '*.ts' '*.tsx' '*.js' '*.mjs' \
  | grep -vE '(^mycelium-client/|/ioc_cfn_svc_api_client/|l9_models\.py$)' \
  | grep -vE '(\.generated\.|\.d\.ts$|/node_modules/|/\.next/)'
```

If the resulting set is empty (e.g. a docs-only PR), say so and stop.

### 3. Dispatch to Haiku

Split the file list into batches (~15–25 files each) and launch one Haiku
sub-agent per batch — **in parallel, in a single message** when there's more than
one. Use `subagent_type: "general-purpose"` and **`model: "haiku"`** (the
cheap-model requirement; `Explore` reads only excerpts and will miss comments, so
don't use it here).

Give each agent this brief, with its file list pasted in:

> Read each listed file and audit **comments and inline documentation only**
> (`#` and docstrings in Python; `//`, `/* */`, JSDoc `/** */` in TS/JS). Flag
> exactly four smells: (1) temporal/historical narration ("used to", "now we",
> "as of PR#", "no longer", "renamed from") — including references to migration
> scaffolding such as build plans, staged-rollout or "phase/rung N" labels, or
> other internal process docs, which describe the effort not the code; (2) overly
> long / exhaustive prose —
> a paragraph where a sentence does; (3) over-referencing transient artifacts —
> GitHub issues (`#142`), PR numbers, or plan-step IDs — especially historical or
> stacked ones; (4) design-justification / conversational residue — comments that
> *defend the approach* or echo *how the code was steered* instead of plainly
> describing it: "Deliberately NOT the X", "rather than Y", arguing against an
> alternative the reader never raised, positioning the file against sibling
> systems for flavor, or editorial flourishes that congratulate the design. A
> one-clause present-tense "X, not Y" that disambiguates a real gotcha is fine;
> the smell is *defending a choice* or re-litigating a rejected alternative — cut
> those to the flat statement of what the code does. References to durable
> artifacts (a named feature/system, a `.claude/skills/*/SKILL.md`, a `docs/*.md`
> design doc, or a source module the comment coordinates with) are legitimate and
> must be KEPT; a lone forward-pointing tracking link on a real
> TODO is also fine. Do not propose removing every reference, and do not flag
> logic, naming, or missing comments. For each finding return: `file:line`, the
> offending comment (trimmed), which smell(s), one-line reason, and a tightened
> rewrite that keeps the load-bearing "why". If a file is clean, say nothing about
> it. Be terse; output a flat list of findings only.

In `--all` mode the agents are read-only auditors regardless of `--fix` — collect
findings first, then do fixes yourself in step 5 so the edits are reviewable.

### 4. Collate & report

Merge the sub-agents' findings into one report, grouped by file, sorted by path
then line. For each: the location, the smell tag, and the before → after rewrite.
Lead with a one-line tally (`N findings across M files`, or `clean`).

### 5. Apply fixes (only if `--fix`)

Apply each accepted rewrite with `Edit`. Re-read before editing. **Do not commit
or push** — leave the working tree dirty for the user to review. After editing,
the user can run the matching quality gate to confirm nothing broke:

- backend: `cd fastapi-backend && uv run ruff check . && uv run ruff format --check . && uv run ty check .`
- cli: `cd mycelium-cli && uv run ruff check . && uv run ruff format --check .`
- openclaw plugin / frontend: the package's own lint (`pnpm lint`).

Report what changed.

---

## Hard rules

- **Cheap model for the heavy lifting.** The reading/judging happens on Haiku
  sub-agents, not on the orchestrator. That's the skill's reason to exist.
- **Comments only.** No logic, naming, or architecture findings — those belong to
  `/code-review`.
- **Don't over-flag references.** Historical and stacked references are the smell;
  pointers to durable artifacts (named features/systems, skills, design docs, a
  coordinating source module) and a lone forward-pointing TODO link are
  legitimate — keep them. References to migration scaffolding (build plans,
  staged-rollout / "phase/rung N" labels, internal process docs) are *not*
  durable — treat them as smell #1. Never suggest stripping references wholesale.
  Err toward leaving borderline cases.
- **Comments describe the code, not the conversation.** Flag justification residue
  — a comment whose reason to exist is to defend the approach against an
  alternative, position the file against a sibling system, or congratulate the
  design. Flat and plain wins. But a single clarifying "X, not Y" that saves a
  reader from a real gotcha is load-bearing — keep it.
- **Never touch generated or vendored files.** `mycelium-client/**`,
  `l9_models.py`, any regenerated CFN client, and `*.d.ts` are off-limits.
- **Read-only unless `--fix`.** No edits, no commits, no PR comments by default.
- **Honest "clean" beats invented findings.**
