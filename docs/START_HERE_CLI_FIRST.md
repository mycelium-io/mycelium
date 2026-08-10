# START HERE — CLI-first participation (decouple the system from the daemon)

> **You own closing a foundational gap.** Right now, being a *participant* in
> mycelium — a SLIM channel member that can receive coordination and reply — is
> only possible **through the daemon**. The daemon's real job is narrow (cold-wake
> an agent that can't wake itself), but membership, keepalive, reply-publishing,
> memory-sync, and presence all got built *inside* it. So an agent that is
> **already awake** (a Claude Code session, a haiku subagent, a shell script,
> Cursor) has no way to participate without running the whole cold-spawn bandaid.
>
> **Design goal: membership is a first-class CLI primitive.** Anything the daemon
> can do must be doable via plain foreground CLI `await`/`respond` commands. The
> daemon becomes a thin auto-waker built *on* that primitive — not the substrate
> everything is trapped inside.

---

## 1. Why this exists

The daemon has always been a **bandaid for one missing capability: Claude (and
similar runtimes) can't natively wake up on an inbound message.** So we built a
background service that holds a SLIM subscription and cold-spawns `claude -p` when
a message arrives.

That's a reasonable bandaid. The mistake is that we **built the system into the
bandaid.** Everything a *member* needs got implemented only inside the connector:

- holding a SLIM group subscription (membership itself),
- the keepalive that stops SLIM from reaping an idle member,
- receiving addressed messages and deciding "is this for me,"
- publishing L9 replies back onto the channel,
- applying `knowledge` writes to the local store (memory sync) + reindex,
- presence hello + self-rejoin + durable-inbox re-serve on reconnect.

None of that is about *waking*. It's about *being a member*. Trapping it in the
waker means: **no daemon → not a member → can't coordinate, can't negotiate,
can't sync.** That's the `participants: []` gap we just hit — the SAO aligner
addresses SLIM members, and a CLI agent isn't one.

Consequences we've already felt: hand-held session management, weird flapping,
the whole coordination stack overfit to a subsystem that was only ever meant to
paper over "no native wake."

---

## 2. The reframe

**Two layers, cleanly separated:**

1. **Membership (the primitive).** Connect to the node, get invited onto a room's
   SLIM group, stay alive (keepalive), receive addressed messages, publish
   replies, apply carried memory. This is generic and runtime-agnostic — it has
   nothing to do with *how* the agent thinks.

2. **Waking (the bandaid, now optional).** For a runtime that can't sit in a
   foreground loop, *something* has to notice an inbound message and start a turn.
   That's the daemon's only real job: **run the membership primitive in the
   background and cold-spawn the agent when it fires.**

Today layer 2 contains layer 1. The goal is to **extract layer 1** into a shared
core and expose it directly as CLI, so:

- an **already-awake** caller (Claude Code, a haiku subagent, a shell script)
  participates by running `await`/`respond` — no daemon, no cold-spawn;
- the **daemon** is rewritten as a small consumer of that same core (background
  `await` + cold-spawn on fire), so the two paths can never drift.

---

## 3. The key insight — the aligner needs no changes

The episode/session work (unique episode ids, transcript tagging, membership
scoping, live episodes) all keys off **SLIM channel membership**: the aligner's
roster is `manager.members(room)`, it @-addresses each member, and it reads their
replies from the transcript as positions.

**If `await` makes the caller a genuine SLIM member, all of that works
unchanged.** A CLI-await agent is in `members(room)`, so it's in the aligner's
roster; its `respond` publishes an L9 `exchange` (role `agent`), which records as
a position. The `participants: []` gap closes not by touching the aligner, but by
making membership reachable without the daemon.

So this is not a coordination rewrite. It's: **lift the membership loop out of the
connector, and give it a front door.**

---

## 4. Holistic responsibility map (daemon → CLI primitive)

Every connector responsibility, and where it goes. (Source:
`mycelium-cli/src/mycelium/daemon/connector.py`.)

| Connector does today | Nature | Where it goes |
|---|---|---|
| `run_connector`: connect + `announce_presence` + `listen_for_session` | **membership** | shared **member-session core**, used by `await` and the daemon |
| `_keepalive_loop` (stay alive ~8s) | **membership** | member-session core (runs for the life of an `await`) |
| receive loop → `should_wake` (addressed to me?) | **membership** | `await` returns the addressed message to its caller |
| `build_reply` + publish L9 exchange (+ position markers) | **membership** | `respond` publishes it |
| `apply_knowledge_message` + `reindex_after_knowledge` | **membership** (memory sync) | member-session core (apply during `await`) |
| presence hello + self-rejoin + durable-inbox re-serve on reconnect | **membership** | member-session core (each `await` reconnect re-serves the missed tail) |
| `_dispatch_one`: **cold-spawn `claude -p`**, then publish | **waking** | stays daemon-only — the one thing that's actually a waker |
| gates: `allow_from` / budget / depth caps | **waking** (spawn protection) | daemon-only (an already-awake caller isn't being spawned) |
| control verbs (`abort`/`status`) | **waking** (act on a running spawn) | daemon-only |

The left column collapses to a single reusable **member-session core**; only the
last three rows (genuinely about *spawning*) stay behind the daemon.

---

## 5. Command surface (proposal)

- **`mycelium await`** — join a room's channel as `--handle`, block until a
  message addressed to that handle arrives (a mediator tick or an `@`-mention),
  print it (prompt + episode + context), and exit. This *is* SLIM membership for
  the duration; on reconnect it re-serves the missed tail (durable inbox), so an
  `await → reason → respond → await` loop never drops coordination.
  - flags: `--room`, `--handle`, `--timeout`, `--json` (machine-readable for
    agents), maybe `--once` vs `--stream`.
- **`mycelium respond`** — publish the caller's reply as an L9 `exchange` for
  `--handle` (parented on the awaited message, carrying any position marker), so
  the aligner records it as a position.
- These supersede the **vestigial CFN-era `mycelium negotiate propose/respond`**
  path that `room.py`'s watch renderer still references — remove/replace it.
- `mycelium watch` stays as the **read-only** human view (SSE, no membership);
  `await`/`respond` are the **participant** path.

The canonical agent loop (daemon-free):

```
mycelium await --room R --handle me --json      # blocks; prints the tick when addressed
# … the agent reasons …
mycelium respond --room R --handle me "my position, moving toward 30% …"
# … loop until a commit:converged / plan arrives …
```

A haiku subagent (or any CLI caller) running this **is a first-class
negotiator** — the demo we wanted falls straight out of the primitive.

---

## 6. Refactor plan

1. **Extract the member-session core.** Pull the membership half of
   `connector.py` (connect, announce_presence, listen_for_session, keepalive,
   receive/`should_wake`, publish/`build_reply`, knowledge-apply, reconnect +
   re-serve) into a runtime-agnostic module (e.g. `daemon/member_session.py` or
   `slim/member.py`). No behavior change — the daemon keeps working.
2. **Build `await`/`respond` on the core.** Foreground commands that use the core
   and hand control to the caller instead of cold-spawning. `--json` output for
   agent consumption.
3. **Rewrite the daemon as a consumer.** `run_connector` becomes: run the core in
   the background, and on an addressed message do the *waking* part (gates +
   cold-spawn `claude -p` + publish). The daemon shrinks to the waker it always
   should have been.
4. **Retire the vestigial `negotiate` CLI path** and the dead
   `coordination_tick` renderer branch.
5. **Verify multi-round.** Confirm the `await → respond → await` reconnect loop
   re-serves reliably within the mediator's round window (`ALIGNER_ROUND_TIMEOUT_S`
   is already tunable — agent think-time is the constraint to size against).

---

## 7. What this unlocks

- **CLI agents are first-class** — Claude Code, haiku subagents, shell, Cursor can
  all coordinate/negotiate/sync with **no daemon**.
- **The daemon stops being load-bearing** — it's an optional convenience for
  can't-self-wake runtimes, and it's built on the same core, so behavior can't
  drift between "daemon" and "CLI" paths.
- **The episode/session system becomes reachable everywhere** — no code changes to
  the aligner; membership is just no longer daemon-exclusive.
- **The demo is trivial afterward** — spawn haiku subagents, each runs
  `await`/`respond`, summon `@aligner`, watch a real episode + plan.

---

## 8. Non-goals / guardrails

- **Don't change the aligner/episode code** to accommodate CLI agents — the point
  is that membership is the seam; if you're editing `aligner.py`, reconsider.
- **Don't delete the daemon** — rebuild it on the core. Can't-self-wake runtimes
  still need a background waker.
- **Keep `watch` read-only** — participation is `await`/`respond`, viewing is
  `watch`. Don't merge them.
- **One core, two consumers** — if the CLI path and the daemon path have separate
  membership implementations, the drift we're fixing comes right back.
