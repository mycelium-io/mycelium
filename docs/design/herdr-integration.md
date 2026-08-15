# herdr × mycelium — what's possible

*Companion to issue #446. Grounded in a live probe of herdr 0.8.0 / socket
protocol 19 and the mycelium `Integration` seam. This is the "whats possible"
deliverable; the PoC that implements Shape 1 lives on branch
`herdr-integration-poc-446` (`mycelium herdr` + opt-in auto-wake in
`agent invoke`).*

## Proven live (the PoC end-to-end)

On `herdr-integration-poc-446`, against a running backend and a real persistent
**Claude Opus** session in a herdr pane (`w2:pV`), the wake path ran end to end:

```
mycelium agent invoke poc-reviewer "…" --room herdr-poc
  → not resident → herdr agent prompt w2:pV "<wake prompt>"
  → the live Claude session woke IN PLACE, reasoned ("check pending
    coordination messages"), ran `mycelium await`, then `mycelium respond`
  → reply landed in the room transcript:
    poc-reviewer [broadcast]: "Confirmed — the herdr wake path delivered this…"
```

The wake mechanism is proven: herdr woke a cold, non-resident agent in place with
full context, and the reply flowed through the *room*, never scraped from the
terminal. Two real seam findings the live run surfaced (below) are the spike's
most valuable output — both are backend-await semantics, not herdr problems.

### Finding 1 — cold-wake races the first-await cursor init

`await`'s per-`(room, handle)` cursor initializes on **first await** to the
*current end* of the transcript (`fastapi-backend/app/routes/participate.py:158`:
"start at the current end so it only sees turns addressed to it from when it began
participating"). The cold-wake ordering is:

1. `invoke` appends `@handle msg` to the transcript,
2. autowake prompts the pane,
3. the agent's **first-ever** await inits its cursor *past* the message → returns
   `message: null`. The message is missed.

This assumption is correct for an already-looping resident (its cursor was
established before the message arrived) but **wrong for cold-wake**, which is the
whole point of the herdr integration. Confirmed live: the first wake's `await`
returned null twice; a *second* invoke (cursor now established) was delivered and
answered. Fix options (backend, not in this PoC): init a freshly-registered
handle's cursor to its registration point / transcript start, or have the wake
establish presence before the coordinating message is posted, or let `await` look
back over recent unconsumed `@`-mentions on first poll.

### Finding 2 — the presence lease outlives actual awaiting

Right after a wake, `_is_resident` (`commands/agent.py:174`, the backend's
`members()` = SLIM members ∪ lease holders) returns `True` because the wake's
`await` refreshed a presence lease — even though the agent has since settled and
is **not** looping. So the *next* `invoke` takes the "resident — it'll pick this
up" branch and skips the wake, but nothing is actually awaiting; the message waits
for the lease to lapse. The lease TTL is a liveness *approximation*; cold-wake
makes the gap observable.

**Fixed in this PR (CLI-side).** The backend runs containerized and is herdr-blind,
so it can't validate its own leases; the CLI is the one layer that reaches both
the backend `/members` API and the local herdr socket. So residence is now
*reconciled* there: for a herdr-mapped handle, herdr's live agent list is
authoritative (`commands/agent.py:_resolve_presence`) — a live+idle pane is woken
over a stale lease, a dead pane reads as stale (queued + warned), and only unmapped
handles fall back to the raw lease. `mycelium herdr ls` surfaces the same
reconciliation as a table (`slim`/`lease` × live pane state → `stale lease` /
`herdr-only` / `in sync`). The remaining backend-side refinement (a shorter lease
when no `--loop` is running) is orthogonal and left to the backend.

These are exactly the "wake semantics" and "lifecycle ownership" open questions
from the issue — now concrete, reproducible, and with `file:line` anchors.

## The one-sentence thesis

Mycelium's hardest unsolved problem is **runtime persistence** — coding agents
are ephemeral, and the old daemon's `claude -p` cold-spawn threw away context
every turn. herdr is precisely the missing layer: a headless server that keeps
agent sessions **alive, addressable, and wakeable** across detach. The division
of labor is clean and non-overlapping:

- **herdr = where agents *live*** — persistent runtime, addressable pane,
  wakeable in place, survives detach.
- **mycelium = how agents *coordinate*** — rooms, the SLIM channel, shared
  memory, the aligner.

They compose. Neither has to absorb the other.

## The gap, precisely

`mycelium agent invoke <handle> "..."` posts an `@`-addressed message to the
room transcript. Two outcomes today (`mycelium-cli/.../commands/agent.py:905`):

- **Resident** (a runtime is looping `mycelium await --loop`): it picks the
  message up on its next poll. 
- **Not resident**: the message "queues on the durable cursor until a runtime
  awaits." Honest, but in practice it **goes to the aether** — nothing wakes,
  because there is nothing to wake. The user has to go find a terminal and start
  `await --loop` by hand.

The cold-spawn daemon that used to fill this gap was removed on purpose: it
re-spawned `claude -p` from zero every turn, discarding all accumulated context
(see CLAUDE.md, "Participation is a CLI primitive"). So the gap is real and
currently unfilled.

**herdr fills it without reintroducing the coupling that rotted openclaw/hermes.**
The wake becomes `herdr agent prompt <that handle's pane> "<coordination
prompt>"` — the agent wakes **in place, with full accumulated context**, runs one
`await` → reason → `respond` cycle, and the reply flows back through the *room*,
not the terminal. Strictly better than cold-spawn.

## What surfaces herdr exposes (verified live)

herdr ships a single `herdr` CLI over a Unix socket
(`~/.config/herdr/herdr.sock`), returning JSON. The surfaces that matter for an
integration:

### 1. Agent control — the wake path

| Command | What it gives us |
|---|---|
| `herdr agent list` | Every live agent as JSON: `agent` (kind), `agent_status` (`idle`/`working`/`blocked`/`done`/`unknown`), `pane_id`, `tab_id`, `workspace_id`, `cwd`, `focused`. This is **liveness + addressability** in one call. |
| `herdr agent get <target>` | One agent's live state. |
| `herdr agent prompt <target> "<text>" --wait [--until S] [--timeout MS]` | **The make-or-break motion.** Atomically injects prompt + Enter into a *persistent* agent and blocks until it settles (`idle`/`done`/`blocked`). This is the exact wake the daemon needed. |
| `herdr agent wait <target> --until <state>` | Block until a state — e.g. wait for `blocked` (a permission/approval prompt) to route to the human. |
| `herdr agent start <name> --kind <k> --pane <id>` | Start a supported agent in an existing shell pane. Kinds include **`pi`, `claude`, `cursor`, `hermes`** — literally the mycelium cast. |
| `herdr agent send-keys` / `read` / `focus` / `rename` | Raw TUI control + scrollback reads. |

**Targeting.** An agent command accepts *either* a unique live agent **name**
(`[a-z][a-z0-9_-]{0,31}`) *or* the **pane id** hosting it (`w2:pV`). Names follow
the pane occupant and **clear when the agent exits** — which is exactly why a
durable `mycelium handle ↔ herdr pane` registry is needed (below).

**Wake semantics (from `agent prompt --help`).** A prompt from a non-working
state must produce an observed lifecycle change within 5 s, else herdr returns
`agent_prompt_stalled` rather than hanging. If the agent is *already* `working`,
that active turn's completion may satisfy `--wait` — so a wake arriving mid-work
is not lost, but it also isn't cleanly queued; the caller has to decide (see open
questions).

### 2. Layout — workspaces / tabs / panes

`herdr workspace|tab|pane` create/split/move/list, all JSON, opaque stable ids
(`w1`, `w1:t1`, `w1:p1`). A herdr **workspace** is a natural unit to map onto a
mycelium **room** (Shape 2). `pane split --env KEY=VALUE` can inject env into a
launched process — a clean way to stamp `MYCELIUM_ROOM`/`MYCELIUM_HANDLE` into a
pane at birth.

### 3. Integration contract — `herdr integration install|uninstall|status`

herdr has a first-class integration surface, but it is **narrower than the name
suggests**: it installs *agent-state hooks* into ~16 known agent runtimes
(`pi`, `claude`, `codex`, `cursor`, `hermes`, …) so herdr can classify their
lifecycle. It plugs a hook script into e.g. `~/.claude/hooks/herdr-agent-state.sh`.
It is **not** a general plugin bus that a third party (mycelium) registers into.

**Implication:** "ship mycelium *as* a herdr integration" (issue Shape 2) is not
what this surface is for. The real composition is the other direction —
**mycelium calls the herdr CLI**, and mycelium installs *its own* skill into the
herdr-managed agent (the same `~/.claude/skills/mycelium` it already installs).
The two skills then coexist in one agent: herdr drives the workspace, mycelium
drives coordination.

### 4. Remote — `herdr --remote <ssh-target>`

herdr attaches to a remote headless server over SSH. This maps almost 1:1 onto
mycelium hub-and-spoke: **herdr owns the remote runtime, mycelium owns the
cross-machine coordination** over the shared SLIM node. Out of scope for the PoC,
but the seam is symmetric.

### The one real limitation (and why it doesn't bite us)

`herdr agent read` **cannot scrape Claude Code's reply text** — Claude runs a
full-screen alt-screen TUI, so the response never lands in herdr's scrollback.
All read sources return only the input box + status bar.

**Non-issue for mycelium:** we never scrape stdout. A mycelium agent self-reports
via `mycelium respond` — the reply flows through the *room*. herdr supplies
**wake + liveness**; mycelium supplies the **reply channel**. The two
responsibilities don't overlap, so herdr's read blindness is invisible to us.

## Do we 100% require herdr for multi-agent coding-agent integration?

**No — and that's a design constraint, not a hedge.** herdr is an *optional* wake
and runtime. The CLI-first `await`/`respond` primitive stays the substrate:

- A user who runs `mycelium await --loop --exec <cmd>` in any terminal is already
  a resident, wakeable agent. No herdr needed.
- herdr's value is that it makes "resident + wakeable" **the default for N agents
  at once**, without the user hand-managing N `await --loop` terminals, and it
  survives laptop-close / detach.

So the honest framing: herdr is the **best available answer to the persistence
gap today**, not a hard dependency. Everything degrades to the pure-CLI path if
herdr is absent. The PoC enforces this: auto-wake is **opt-in and fail-soft** —
if herdr is missing, unreachable, or has no pane mapped, `agent invoke` falls
straight back to the honest "queued on the cursor" behavior.

Where herdr genuinely *is* required: the "close the laptop and agents still get
woken later" story (cold-start-on-demand) needs *some* persistent runtime host.
herdr is the cleanest one that already recognizes our exact agent cast.

## The four shapes (from the issue), re-scoped after the probe

| Shape | Verdict | Notes |
|---|---|---|
| **1. herdr as a wake target / connector** | **Build first (the PoC).** | Replace cold-spawn with `herdr agent prompt`. Slots under the existing `Integration` seam; strictly better than the removed daemon. |
| **2. mycelium *as a herdr integration*** | **Reframe.** | herdr's `integration install` is agent-state hooks, not a plugin bus. The composition is mycelium-calls-herdr + mycelium installs its own skill into herdr agents. Still yields "a herdr workspace is a coordination space," just built the other way. |
| **3. liveness in the UI** | **Built.** | `mycelium herdr sync [--watch]` (host-side) mirrors `agent list`'s `idle`/`working`/`blocked` into the backend presence surface (new `POST /sessions/herdr-presence`, `kind="herdr"` overlaid onto `presence()` but never `members()`); the frontend renders a status-colored badge per agent. Backend is herdr-blind (containerized), so the CLI is the only layer that sees both — hence the host-side sync loop (the honest home for a poller after the daemon's removal). |
| **4. remote / hub-and-spoke** | **Symmetric, later.** | `--remote` maps onto hub-and-spoke; defer until single-host is proven. |
| **Bonus: aligner's Pi brain as a herdr `pi` agent** | **Plausible.** | herdr recognizes `pi`; the aligner's persistent Pi session could run herdr-hosted instead of backend-hosted. Interesting, not on the critical path. |

## Clean user stories

**Story A — "drop N agents in a room, then just talk to them."**

```
# once: agents live in herdr, addressable
herdr agent start reviewer --kind claude --pane w2:pV
herdr agent start docs     --kind claude --pane w2:pW

# once: bind mycelium handles to those panes
mycelium herdr map reviewer w2:pV --room design
mycelium herdr map docs     w2:pW --room design

# thereafter: coordination just works, no babysitting terminals
mycelium agent invoke reviewer "review the auth diff"   # herdr wakes pV in place
mycelium @reviewer ... @docs ...                         # aligner mediates; each wakes on its tick
```

The user never hand-runs `await --loop`. Each invoke/tick wakes the right
persistent agent **with its full context intact**, and replies land in the room.

**Story B — "close the laptop, come back, agents caught up."**

Detach herdr (session survives). A teammate `@`-mentions your agent. On the next
wake (a scheduled `mycelium herdr wake`, or you re-attaching), herdr prompts the
still-alive pane; the agent processes the queued turn from the durable cursor.
Nothing went to the aether.

**Story C — "an agent is stuck and I should know."**

`mycelium herdr status` (or the room inspector, Shape 3) shows `reviewer:
blocked` — herdr recognized a permission prompt. Route it to the human via the
mycelium consent path instead of silently stalling.

## Open questions (carried from the issue, sharpened by the probe)

- **Handle ↔ pane durability.** herdr names clear on agent exit; pane ids are
  stable but a pane can be closed. The registry must survive agent restarts and
  detect staleness (map points at a pane that's now empty or hosts a different
  agent). *PoC answer: a JSON registry keyed by `room/handle`, validated against
  live `agent list` at wake time; a stale mapping fails soft.*
- **Wake-while-working.** `agent prompt` on a `working` agent may match the
  *current* turn's completion, not our new turn. Options: reject (let the cursor
  hold it), queue (re-prompt after `idle`), or rely on the agent's own
  `await --loop` if it's resident. *PoC answer: only auto-wake when the agent is
  `idle`/`done`; if `working`/`blocked`, fall back to the cursor.*
- **Reply path ownership.** The herdr-spawned agent must have the mycelium skill
  so it `respond`s on its own. *PoC answer: `mycelium adapter add claude-code`
  installs the skill; the wake prompt tells the agent to run the await/respond
  cycle.*
- **Lifecycle ownership.** Does mycelium spawn panes/agents or only drive
  user-created ones? *PoC answer: only drive existing ones (map, don't spawn).
  Spawning is a later, riskier increment.*
- **API stability.** Is protocol 19 a contract to build against? Versioning /
  compat story? The bridge pins nothing and treats non-zero exit + JSON-on-stderr
  as the error contract herdr documents.
- **Identity.** herdr agents are local processes with no per-agent identity;
  this rides the same D1 (JWT/SPIRE) prerequisite as everything else before
  anything hosted/multi-user. herdr does not change that calculus.

## Determining which herdr agents belong to which room

herdr and rooms are **orthogonal namespaces** — herdr groups agents by
workspace → tab → pane → cwd; a room is a coordination namespace. Nothing in a
herdr agent intrinsically says "I belong to room X," so *some* policy supplies the
binding. And "add an agent to a room" is really **two layers**: (1) *binding* a
pane to a room+handle, and (2) *enrollment* — actually becoming a member by
registering a manifest **and** joining (a wake, or `await --loop`). A binding
alone doesn't make an agent appear as a member — which is exactly why a freshly
mapped-but-unwoken agent reads `herdr-only (not joined)` in `herdr ls`.

The PoC ships the **workspace → room** policy (design Shape 2), because a herdr
workspace already *is* "a set of agents working together":

```
mycelium herdr enroll --workspace w2 --room design [--kind claude] [--wake] [--dry-run]
```

For every live agent in the workspace it registers a `claude_code` manifest, binds
handle↔pane, and (with `--wake`) wakes it to join — idempotent, so re-running skips
what's already enrolled. The **handle is the tab name** by default
(`--name-from tab`; `pane` uses the pane id), sanitized to the manifest handle rule
and disambiguated by the pane suffix on collision — so `w2` enrolls as
`@pr-review`, `@test-area`, `@herdr`, … rather than opaque pane ids. Verified live
against the running stack.

Other policies are possible on the same seam (cwd/repo → room; the agent
self-selecting via `room use`) — workspace→room is the default because it's the
one that needs the least per-agent input. Lifecycle stays honest: enroll only
*drives* agents the user already started; it never spawns panes.

## Wake-on-mention (the bidirectional bridge) + a reliability finding

The `herdr sync` bridge is **bidirectional**: presence *up* (Shape 3) and wake
commands *down*. When a tag `@`-mentions a herdr-present handle, the backend
(herdr-blind) can't wake it — so it **enqueues a doorbell**; the host-side bridge
drains it and runs `herdr agent prompt`. Two properties fell out of live use:

- **Hold-until-idle.** A tag for a `working`/`blocked` agent is *held* in the
  backend queue and only *released* once herdr shows it `idle` — so a mention
  mid-turn is delivered when the agent frees up, not dropped. (TTL'd so a
  never-idle agent can't hold a tag forever.)
- **The wake is a doorbell, not a payload.** It carries no message text — just
  "you have messages waiting in room X, run `mycelium room messages …`." The
  agent reads the transcript itself (source of truth, ordered, nothing lost) and
  keeps agency to defer. This dissolved an accumulate/dedup/first-await-cursor
  mess that came from trying to hand the messages over inline.

**Reliability finding — herdr's Claude state is title-scraped.** With the herdr
Claude state-hook *not* installed, herdr infers `working` by matching the
terminal-title spinner (`osc_title_working`, priority 1100) — which outranks the
idle `❯`-prompt-box rule (`live_prompt_box`, 950) and can stick after an
interrupted turn, so a pane reads `working` while actually idle and its held wake
never releases. The hold/doorbell make *our* layer robust, but authoritative
state needs `herdr integration install claude` (real lifecycle hooks) rather than
title heuristics. Also observed: **the enrolled agent can *be* your active
session** (mapping `@herdr` → the very pane you're driving), and waking a
`working` agent is correctly declined.

> **Security boundary (hard prerequisite).** The two new endpoints
> (`POST /sessions/herdr-presence`, `GET /sessions/herdr-wakes`) are
> **unauthenticated**, and a wake ultimately runs `herdr agent prompt` against a
> local coding-agent pane — i.e. room-post content can steer a local agent. This
> is single-user-local PoC only; it must be architected around the D1
> **JWT/SPIRE** identity work (the bridge authenticating as a real principal,
> per-agent authz on wake) before anything hosted or multi-user.

## Non-goals

- Not replacing `await`/`respond` — herdr is an optional wake, not a requirement.
- Not spawning panes/agents from mycelium (yet) — the PoC only *drives* agents
  the user already created.
- Not scraping agent stdout — the reply channel is the room, always.
</content>
</invoke>
