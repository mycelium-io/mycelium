# CLI Pattern Audit

*What agents will assume, what breaks those assumptions, and what to fix.*

The test: an agent that has never read our docs tries to use the CLI based on
patterns it learned from git, docker, kubectl, redis-cli, npm, gh. Where does
it get confused?

## Command Inventory

```
mycelium
├── init, install, up, down, status, logs   # instance lifecycle
├── watch, synthesize, catchup              # top-level shortcuts
├── room   ls, create, set, delete, join, await, watch, synthesize, respond, delegate
├── message   propose, respond, query
├── memory   set, get, ls, search, rm, subscribe, catchup, status, work, decisions, context
├── config   show, set, get
├── adapter   add, remove, ls, status
└── docs   ls, search
```

## What Fits

**memory set/get/ls/rm/search** — Universal KV store pattern. Every agent
will reach for these correctly.

**config show/set/get** — Standard config pattern (git config, npm config).

**room create/delete/ls** — Standard CRUD. `room ls` matches `docker ps`,
`kubectl get pods`, etc.

**up/down/status/logs** — Docker Compose muscle memory. Perfect.

**adapter add/remove/ls/status** — Package manager pattern (apt, brew). Clean.

**docs ls/search** — `man`/`--help` pattern. Fine.

## What Breaks

### 1. `room respond` vs `message respond` — name collision

An agent in a negotiation will see "respond" in its tick and try either one.
They do different things:
- `message respond accept` — SSTP-validated negotiation reply
- `room respond SESSION_ID --agent foo --response "text"` — raw message post

An agent will absolutely confuse these. `room respond` is also weird because
it takes a SESSION_ID positional but it's really just posting a message to a
room. It's a lower-level version of `message respond`.

**Suggestion:** Rename `room respond` to `room send` or `room post`. That
breaks the collision and better describes what it does (posting a raw message).
Or remove it entirely — `message query` already covers raw message posting.

### 2. `room delegate` — no established pattern

No common CLI has a `delegate` subcommand. An agent won't guess this exists.
It's also semantically unclear — it posts a "delegate" message type, but
what does that mean from the agent's perspective?

**Suggestion:** If this is used for task routing, make it discoverable via the
`await` tick responses. If it's rarely used, consider removing it from the
CLI and leaving it as an API-only operation.

### 3. `room await` — unusual verb

Agents know `watch`, `wait`, `listen`, `poll`. `await` is a Python keyword,
not a CLI pattern. `kubectl wait` exists but it waits for a condition, not a
message.

**Suggestion:** `room wait` is more conventional. Or `room listen` since the
agent is listening for its next tick. The `--handle` flag being required also
feels odd — in most CLIs, identity is configured once, not passed per-command.

### 4. `room set` means "set active room" — overloaded verb

`room set lab` sets the active room. But `config set` sets a config value,
`memory set` writes a memory. An agent seeing the pattern will try
`room set --mode async` expecting to update room properties.

**Suggestion:** `room use lab` or `room switch lab`. Matches `nvm use 18`,
`kubectl config use-context`, `pyenv shell 3.12`. The verb "use" means
"make this the active thing" without colliding with "set a value."

### 5. `room watch` exists twice

`mycelium watch` (top-level shortcut) and `mycelium room watch` are the same
function. Fine for discoverability, but `mycelium watch` takes a positional
room name while the room is usually configured. An agent might try
`mycelium watch` with no args and get confused when it needs a room name
but `mycelium room watch` uses the active room.

**Suggestion:** Make both behave identically — fall back to active room when
no arg is provided. (May already work, but verify.)

### 6. `memory catchup` vs `mycelium catchup` — same thing, two places

`mycelium catchup` is a top-level shortcut to `memory catchup`. Fine. But
the catchup endpoint is on `/rooms/{room}/catchup`, which makes it
conceptually a room operation, not a memory operation. An agent might look
for `room catchup`.

**Suggestion:** Keep the top-level shortcut (it's the most common entry
point). Move the canonical command to `room catchup` and alias it from
`memory catchup`. The data is room-scoped, the synthesis is room-scoped,
it belongs under room.

### 7. `message` group is a protocol, not a resource

`room`, `memory`, `config`, `adapter` are all nouns (resources). `message`
is also a noun, but the commands under it (`propose`, `respond`, `query`)
are negotiation protocol verbs, not message CRUD. An agent wanting to
read messages will try `message ls` or `message list` and find nothing.

There's no way to list or read messages through the CLI at all.

**Suggestion:** Either:
- (a) Add `message ls` / `message history` for reading room messages, making
  the group a proper resource. Agents trying to debug "what happened in this
  room" have no CLI path for that today.
- (b) Rename the group to `negotiate` — makes the protocol purpose explicit
  and stops agents from expecting CRUD operations. `mycelium negotiate propose`,
  `mycelium negotiate respond`.

Option (b) is more honest about what this group does, but (a) adds real
utility. Could do both: rename to `negotiate` and add `message ls` as a
separate read-only group or under `room`.

### 8. No `memory update` — agents will try it

The upsert pattern requires `memory set KEY VALUE --update`. An agent that
wants to update a value will try `memory update KEY VALUE` because that's
the CRUD verb. It doesn't exist.

**Suggestion:** Either add `memory update` as an alias for `set --update`,
or (simpler) just drop the `--update` guard entirely. The backend already
handles upserts atomically with version tracking. The guard exists to prevent
accidental overwrites, but agents don't make "accidents" — they always know
what key they're writing. The `--update` flag is a human safety net that
makes agent usage clunky.

### 9. `adapter add`/`remove` vs `install`/`uninstall`

The package manager pattern is split: `add`/`remove` (npm style) vs
`install`/`uninstall` (apt/pip style). Both are established, but the CLI
already uses `mycelium install` at the top level. Having `adapter add` next
to top-level `install` is a mild inconsistency.

**Suggestion:** Low priority. Either is fine. If anything, `adapter install`
would be more consistent with the top-level `install`, but not worth a
breaking change.

### 10. `--handle/-h` vs `--handle/-H` inconsistency

Memory commands use `--handle/-h`. Message commands use `--handle/-H` (to
avoid collision with `--help`). Room commands use `--handle/-H`. An agent
will get `-h` vs `-H` wrong constantly.

**Suggestion:** Pick one. `-H` is safer since `-h` collides with `--help`
in some contexts. Standardize on `--handle/-H` everywhere, or use a
different flag name entirely (`--as`, `--agent`, `--identity`). `--as`
is nice and short: `mycelium memory set status/x "done" --as julia-agent`.

## How This Connects to the Memory Direction

(See `scratchpad/memory-service-direction.md` for full context.)

The CLI pattern issues above are **friction that prevents agents from using
memory well**. The memory system is the part of Mycelium that solves real
pain today — Marc's agent forgot about the cron job. The structured key
conventions (`work/`, `status/`, `decisions/`, `context/`) and the commands
that were built on top of them (`memory status`, `memory work`, etc.) are
the right direction.

But agents won't use memory correctly if the CLI fights them:

- `--update` guard on `memory set` means agents avoid overwriting, so they
  write fewer memories or error out silently
- `--handle` inconsistency means agent attribution is wrong on memories
- No `message ls` means agents can't review what happened in a room to
  decide what's worth persisting
- `room set` confusion means agents might not even be pointed at the right
  room when they write

These are the input end of the pipeline. Fix the ergonomics → agents write
more memories → catchup/synthesis gets better → continuity improves.

The procedural memory question isn't about cognitive science taxonomy. It's
about whether an agent can come back tomorrow and pick up where it left off.
That's a CLI ergonomics problem as much as it is a storage problem.

## Priority Ranking

| # | Issue | Impact | Effort |
|---|-------|--------|--------|
| 1 | `respond` collision | High — agents will hit this | Low |
| 4 | `room set` overloaded | High — misleading | Low |
| 7 | `message` group identity crisis | Medium — missing read path | Medium |
| 8 | No `memory update` | Medium — agents will try it | Low |
| 10 | `-h` vs `-H` | Medium — constant small friction | Low |
| 3 | `room await` unusual verb | Low-medium — works once learned | Low |
| 6 | `catchup` location | Low — shortcut covers it | Low |
| 2 | `room delegate` undiscoverable | Low — niche feature | Low |
| 5 | `watch` behavior mismatch | Low — probably already works | Low |
| 9 | `add` vs `install` | Low — cosmetic | Low |
