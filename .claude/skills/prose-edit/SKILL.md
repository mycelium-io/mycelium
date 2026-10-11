---
name: prose-edit
description: How to write and edit prose in this repo, and what to look for when reviewing it. Covers code comments and docstrings, CLAUDE.md, the docs, READMEs, skill files, PR descriptions, commit messages and text in the app. Use when writing or editing any of these, when reviewing a PR's writing, or when asked to "edit prose", "tidy comments", "audit comments", "check the docs' wording" or "prose-edit".
user_invocable: true
---

# Writing and editing prose

These are guidelines, not a procedure. Use them when you write, when you edit,
and when you review someone else's writing.

## The test

Picture a teammate who wasn't in the conversation that produced the text.
After reading it once, can they say **what happens, to whom, and when**? If
not, rewrite it as plain cause and effect.

## What to look for

### 1. Clever instead of clear

This is the most common problem, and the hardest to spot in your own writing.
The text tries to be terse and poetic at once, loses the meaning on the way,
and sounds pretentious.

Signs:

- **Slogans and parallel triplets** that have rhythm but no content.
- **Code that "acts":** "a mention asks", "the hub carries it", "a ping says the
  thread moved". Say what the code does instead.
- **Abstract nouns where the behavior should be:** "a wake", "the floor", "the
  seam", used as if the reader already knows them.
- **No who, what or when:** "it's held" (held by what, until when?).

Before:

> A mention asks; `@~` names; `@!` interrupts.

After:

> A message to an agent (`@foo`) reaches it when it finishes what it's working
> on. A message that interrupts an agent (`@!foo`) reaches it right away, even
> if it's working. A message that names an agent (`@~foo`) doesn't wake it at
> all.

### 2. History instead of what the code does now

The text describes how the code got here: "this used to…", "now we…", "replaces
the old…", "no longer", "renamed from", "as of PR #412". Git holds the history.
Describe the code as it is.

References to the work that produced the code count too: build plans, rollout
phases, "step 4 of the migration". They describe the effort, not the code.

Before:

```python
# This used to route Bedrock models through litellm.acompletion like everything
# else, but as of PR #412 that no longer works, so now we use a worker thread.
```

After:

```python
# litellm.acompletion hangs for Bedrock models, so they use the sync
# completion() on a worker thread.
```

### 3. Defending the design

The text argues for the approach, or against an alternative the reader never
raised. It's what's left over when someone said "do it this way, not that way"
and the reasoning got written into the file. Signs: "deliberately not X",
"rather than Y", comparing the code to other parts of the system for flavor,
and praise for the design ("the clean way").

Cut it down to what the code does and the reason it needs, if any. A short "X,
not Y" is fine when it stops a reader from making a real mistake.

### 4. Issue and PR numbers as decoration

`(#334)`, "see also #117 and #142", "PR #128". These go stale and don't help
the reader. Keep a reference only when it points at something lasting that
explains what the code can't: a skill, a doc, a named system, or the module
the code works with. A single link on a real `TODO` is fine too.

### 5. Coding-agent shorthand

Writing that reads like one agent briefing another: clipped fragments, chains
of colons, and jargon verbs ("rides", "lifted onto", "folds", "mints", "the
wire", "load-bearing"). Write full sentences. Define an internal term the first
time it appears, or use a plain word instead.

### 6. Too much

A paragraph where a sentence would do. Restating the code line by line.
Explaining what's already clear from the names. In comments, match how much
the surrounding code says, and say why rather than what.

### 7. Punctuation and tone

- **No em dashes (`—`).** Use a period, a comma, a colon or parentheses.
- **No theatrical phrasing:** "make no mistake", "non-negotiable", "the honest
  ceiling", "that is precisely the moment". State the fact and stop.
- **No comma-chunked sentences,** where a sentence ends, hits a comma, and
  tacks on an "or" or "and" as an afterthought. Write it the way you'd say it
  in one breath, or split it into two sentences.

## Where things go

- **Code comments** say what the code does and why, in the present tense.
- **CLAUDE.md** holds the design and the reasons for it. It's prose for people
  too, so everything above applies there.
- **The docs** are for people using Mycelium: start with what they're trying to
  do and why, then how.
- **PR descriptions** say what changed and why, and what wasn't tested. Never
  write `@name` in anything that goes to GitHub: room handles are real GitHub
  users, and GitHub notifies them.

## When reviewing

- Read a PR's prose as well as its code: comments, CLAUDE.md, docs, skill
  files and the description.
- Quote the sentence, say which problem it has, and suggest a rewrite.
- Text that's already clear is a fine result. Don't invent findings, and don't
  rewrite text that works just to make it yours.
- Leave generated files alone: `mycelium-client/`, `*.d.ts`, and the generated
  docs under `docs/` (edit their markdown sources and regenerate instead).
